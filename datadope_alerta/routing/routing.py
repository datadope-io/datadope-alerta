import inspect
import logging
from typing import List

from alerta.models.enums import Status

from datadope_alerta import CONFIG_PLUGINS, ALERTER_IGNORE, NormalizedDictView, ContextualConfiguration
from datadope_alerta import GlobalAttributes as GAttr, RecoveryActionsFields
from datadope_alerta import thread_local, initialize, AlertIdFilter
from datadope_alerta.backend.flexiblededup.models.recovery_actions import RecoveryActionData
from datadope_alerta.plugins import AlerterStatus
from datadope_alerta.plugins.iom_plugin import IOMAlerterPlugin
from datadope_alerta.plugins.recovery_actions.plugin import RecoveryActionsPlugin

logger = logging.getLogger(__name__)

_plain_plugins: List[str] | None = None
_alerters_plugins: List[str] | None = None
_recovery_actions_plugin: str | None = None


def initialize_plugins(plugins_object, config):
    logger.addFilter(AlertIdFilter.get_instance())
    initialize()
    all_plugins = config.get(CONFIG_PLUGINS, [])
    alerters = []
    plugins = []
    recovery_actions_plugin: RecoveryActionsPlugin | None = None
    recovery_actions_plugin_name: str | None = None
    for plugin in all_plugins:
        plugin_object = plugins_object.get(plugin)
        if isinstance(plugin_object, RecoveryActionsPlugin):
            recovery_actions_plugin_name = plugin
            recovery_actions_plugin = plugin_object
        elif isinstance(plugin_object, IOMAlerterPlugin):
            plugin_object.alerter_name = plugin
            plugin_object.global_app_config = config
            alerters.append(plugin)
        else:
            plugins.append(plugin)
    if recovery_actions_plugin:
        recovery_actions_plugin.alerter_plugins = {y.alerter_name: y for x, y in plugins_object.items()
                                                   if x in alerters}
        global _recovery_actions_plugin
        _recovery_actions_plugin = recovery_actions_plugin_name
    logger.info("Configured IOMetrics alerter plugins: %s", alerters)
    return plugins, alerters


def rules(alert, plugins, config):  # noqa
    thread_local.alert_id = alert.id
    thread_local.alerter_name = 'routing'
    try:
        global _plain_plugins, _alerters_plugins
        if _plain_plugins is None:
            _plain_plugins, _alerters_plugins = initialize_plugins(plugins, config)

        result = _plain_plugins.copy()

        stack = inspect.stack()
        routing_request = stack[2].function if len(stack) > 2 else None
        thread_local.operation = routing_request

        if alert.status in (Status.Blackout, Status.Expired):
            # Alerters and recovery actions are not executed during blackout or if expired
            logger.debug("Ignoring alerters for blackout or expired alerts")
            missing = [x for x in result if x not in plugins]
            if missing:
                logger.warning("Some routed plugin is not configured: %s", ', '.join(missing))
                result = [x for x in result if x in plugins]
            return [plugins[x] for x in result]

        alert_attributes = NormalizedDictView(alert.attributes)
        alerters = ContextualConfiguration.get_global_attribute_value(GAttr.ALERTERS, alert,
                                                                      global_config=config)

        recovery_actions_config = alert_attributes.get(GAttr.RECOVERY_ACTIONS.var_name)
        if recovery_actions_config and isinstance(recovery_actions_config, dict) \
                and recovery_actions_config.get(RecoveryActionsFields.ACTIONS.var_name):
            recovery_action_data = RecoveryActionData.from_db(alert_id=alert.id)
            ra_status = None if recovery_action_data is None else recovery_action_data.status
            if routing_request == 'process_status':
                # status change managed by the plugin
                result.append(_recovery_actions_plugin)
                logger.debug("Ignoring alerters. Managed by recovery_actions plugin")
                missing = [x for x in result if x not in plugins]
                if missing:
                    logger.warning("Some routed plugin is not configured: %s", ', '.join(missing))
                    result = [x for x in result if x in plugins]
                return [plugins[x] for x in result]
            if alert.status != Status.Closed:
                if ra_status:
                    # Recovery actions already active/executed. Do not involve alerters or recovery action plugin
                    logger.debug("Ignoring alerters. Executing recovering actions")
                else:
                    # Recovery actions not launched yet. Only involve recovery action plugin
                    result.append(_recovery_actions_plugin)
                    logger.debug("Ignoring alerters. Waiting to execute recovery actions.")
                missing = [x for x in result if x not in plugins]
                if missing:
                    logger.warning("Some routed plugin is not configured: %s", ', '.join(missing))
                    result = [x for x in result if x in plugins]
                return [plugins[x] for x in result]

        # Include recovery actions plugin if exists to ensure pre_receive is called.
        # pre_receive must ensure recoveryActions attribute will be formed properly so routing
        # can check it to decide post_receive plugins.
        # post_receive method of recovery actions plugin must do nothing
        # if no recovery action is configured for the alert as
        # it is going to be invoked even if no recovery actions are configured.
        if alert.status != Status.Closed and _recovery_actions_plugin:
            result.append(_recovery_actions_plugin)

        if alerters:
            for alerter in alerters:
                if alerter == ALERTER_IGNORE:
                    continue
                if alerter in plugins:
                    if routing_request == 'process_status':
                        # status change managed by the plugin
                        result.append(alerter)
                        continue
                    alerter_name = getattr(plugins[alerter], 'alerter_name',
                                           plugins[alerter].name.replace('.', '_').replace('$', '_'))
                    alerter_status = AlerterStatus.from_db(alert_id=alert.id, alerter_name=alerter_name)
                    if alerter_status in (AlerterStatus.Recovered, AlerterStatus.Recovering):
                        # If alerter has already managed the recovery: ignore
                        logger.info("Alerter %s already sent recovery for '%s'", alerter, alert)
                        continue
                    if routing_request != 'process_action' \
                            and alerter_status not in (AlerterStatus.New, AlerterStatus.Processed) \
                            and alert.status != Status.Closed:
                        # If alerter is processing the alert and alert is not closed: ignore
                        logger.info("Alerter %s already sent '%s'", alerter, alert)
                        continue
                    if routing_request == 'process_action' \
                            and alerter_status in (AlerterStatus.Recovering, AlerterStatus.Recovered):
                        # If alerter is processing the alert and alert is not closed: ignore
                        logger.info("Action processing is ignored in recovered alerter '%s' for alert '%s'",
                                    alerter, alert)
                        continue
                    if alerter_status == AlerterStatus.New and alert.status == Status.Closed:
                        # If alert is closed before start processing: ignore
                        logger.debug("Alerter %s received recovery before start processing '%s'", alerter, alert)
                        continue
                    result.append(alerter)
                else:
                    logger.warning("Plugin for alerter %s not configured. Check 'PLUGINS' configuration variable.",
                                   alerter)
        else:
            logger.info("No alerter configured in attribute '%s'", GAttr.ALERTERS.var_name)
        missing = [x for x in result if x not in plugins]
        if missing:
            logger.warning("Some routed plugin is not configured: %s", ', '.join(missing))
            result = [x for x in result if x in plugins]
        logger.debug("Returning plugins: %s", result)
        return [plugins[x] for x in result]
    finally:
        thread_local.alerter_name = None
