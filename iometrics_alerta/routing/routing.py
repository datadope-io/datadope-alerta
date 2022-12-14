import inspect
import logging

from alerta.models.enums import Status

from iometrics_alerta import CONFIG_PLUGINS, ALERTER_IGNORE, ConfigKeyDict, safe_convert
from iometrics_alerta import AlerterProcessAttributeConstant as AProcC
from iometrics_alerta import GlobalAttributes as GAttr
from iometrics_alerta.plugins import AlerterStatus
from iometrics_alerta.plugins.iom_plugin import IOMAlerterPlugin

logger = logging.getLogger(__name__)

_plain_plugins = None
_alerters_plugins = None


def initialize_plugins(plugins_object, config):
    all_plugins = config.get(CONFIG_PLUGINS, [])
    alerters = []
    plugins = []
    for plugin in all_plugins:
        plugin_object = plugins_object.get(plugin)
        if isinstance(plugin_object, IOMAlerterPlugin):
            plugin_object.alerter_name = plugin
            plugin_object.global_app_config = config
            alerters.append(plugin)
        else:
            plugins.append(plugin)
    logger.info("Configured IOMetrics alerter plugins: %s", alerters)
    return plugins, alerters


def rules(alert, plugins, config):  # noqa
    global _plain_plugins, _alerters_plugins
    if _plain_plugins is None:
        _plain_plugins, _alerters_plugins = initialize_plugins(plugins, config)

    result = _plain_plugins.copy()

    stack = inspect.stack()
    routing_request = stack[2].function if len(stack) > 2 else None
    if routing_request == 'process_action':
        # actions not manage by iometrics plugins -> manage through status change
        return [plugins[x] for x in result]

    if alert.status == Status.Blackout:
        # Alerters are not executed during blackout
        return [plugins[x] for x in result]

    alerters = safe_convert(ConfigKeyDict(alert.attributes).get(GAttr.ALERTERS.var_name, []), list)
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
                alerter_status = AlerterStatus(alert.attributes
                                               .get(AProcC.ATTRIBUTE_FORMATTER.format(alerter_name=alerter_name), {})
                                               .get(AProcC.FIELD_STATUS))
                if alerter_status in (AlerterStatus.Recovered, AlerterStatus.Recovering):
                    # If alerter has already managed the recovery: ignore
                    logger.info("Alerter %s already sent recovery for '%s'", alerter, alert)
                    continue
                if alerter_status != AlerterStatus.New and alert.status != Status.Closed:
                    # If alerter is processing or has processed the alert and alert is not closed: ignore
                    logger.info("Alerter %s already sent '%s'", alerter, alert)
                    continue
                if alerter_status == AlerterStatus.New and alert.status == Status.Closed:
                    # If alert is closed before start processing: ignore
                    logger.info("Alerter %s received recovery before start processing '%s'", alerter, alert)
                    continue
                result.append(alerter)
            else:
                logger.warning("Plugin for alerter %s not configured. Check 'PLUGINS' configuration variable.", alerter)
    else:
        logger.info("No alerter configured in attribute '%s'", GAttr.ALERTERS.var_name)
    return [plugins[x] for x in result]
