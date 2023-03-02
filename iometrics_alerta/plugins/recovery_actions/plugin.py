from datetime import datetime

from pkg_resources import iter_entry_points
from typing import Optional, Any

from alerta.database.backends.flexiblededup.models.recovery_actions import RecoveryActionsStatus, RecoveryActionData
from alerta.models.alert import Alert
from alerta.models.enums import Status
from alerta.plugins import PluginBase

from iometrics_alerta import DateTime, NormalizedDictView, ContextualConfiguration as CConfig, safe_convert, \
    VarDefinition, get_config, thread_local
from iometrics_alerta import get_hierarchical_configuration
from iometrics_alerta import GlobalAttributes
from iometrics_alerta import RecoveryActionsFields as RAConfigFields

from iometrics_alerta.plugins import getLogger
from iometrics_alerta.plugins.bgtasks.recovery_actions import launch_actions, do_alert, fill_result, revoke_task

logger = getLogger(__name__)


class RecoveryActionsPlugin(PluginBase):
    _recovery_actions_providers = None

    @staticmethod
    def initialize_recovery_actions_providers():
        entry_points = {}
        for ep in iter_entry_points('alerta.recovery_actions.providers'):
            logger.info("Recovery actions provider '%s' found.", ep.name)
            entry_points[ep.name] = ep
        return entry_points

    def __init__(self):
        super().__init__()
        if self._recovery_actions_providers is None:
            self._recovery_actions_providers = self.initialize_recovery_actions_providers()
        self.alerter_plugins = None  # Filled in during first routing invocation

    @staticmethod
    def get_processing_delay(alert, action_delay):
        now = datetime.utcnow()
        create_time = alert.create_time or now
        consumed_time = DateTime.diff_seconds_utc(now, create_time)
        return max(2, action_delay - consumed_time)

    def pre_receive(self, alert: 'Alert', **kwargs) -> 'Alert':
        thread_local.alert_id = alert.id
        thread_local.alerter_name = 'recovery_actions'
        app_config = kwargs['config']
        recovery_actions_key = GlobalAttributes.RECOVERY_ACTIONS.var_name
        ra_config = get_config(key=recovery_actions_key, type=dict, config=app_config)

        # Configuration from alert
        alert_attributes = NormalizedDictView(alert.attributes)
        ra_alert_config = NormalizedDictView(safe_convert(
            alert_attributes.get(recovery_actions_key, {}), dict))

        ordered_configs = [ra_alert_config, ra_config]

        recovery_actions_config = {}
        provider_var = RAConfigFields.PROVIDER
        provider = get_hierarchical_configuration(provider_var, ordered_configs)
        recovery_actions_config[provider_var.var_name] = provider
        config_obj = RAConfigFields()
        for field_name in config_obj.__dir__():
            if not field_name.startswith('_') and field_name.upper() == field_name:
                field = getattr(config_obj, field_name)
                if isinstance(field, VarDefinition) and field.var_name != provider_var.var_name:
                    key = field.var_name
                    value = get_hierarchical_configuration(field, ordered_configs, [provider])
                    if value is not None:
                        recovery_actions_config[key] = value

        # Get global values for some vars if not filled for recovery actions.
        from_global_if_null = [
            (RAConfigFields.ALERTERS, GlobalAttributes.ALERTERS),
            (RAConfigFields.ACTION_DELAY, CConfig.ACTION_DELAY)
        ]
        for specific, generic in from_global_if_null:
            key = specific.var_name
            recovery_actions_config[key] = recovery_actions_config.get(
                key, CConfig.get_global_attribute_value(generic, alert, global_config=app_config))

        recovery_actions_config[RAConfigFields.ALERTERS.var_name] = \
            [x for x in recovery_actions_config[RAConfigFields.ALERTERS.var_name]
             if x not in recovery_actions_config[RAConfigFields.ALERTERS_ALWAYS.var_name]]

        if recovery_actions_config.get(RAConfigFields.ACTIONS.var_name):
            # If no action configure, ignore.
            alert_attributes[recovery_actions_key] = recovery_actions_config
        thread_local.alerter_name = None
        return alert

    def take_action(self, alert: 'Alert', action: str, text: str, **kwargs) -> Any:
        pass

    def take_note(self, alert: 'Alert', text: Optional[str], **kwargs) -> Any:
        pass

    def delete(self, alert: 'Alert', **kwargs) -> bool:
        return True

    def post_receive(self, alert: 'Alert', **kwargs) -> Optional['Alert']:
        thread_local.alert_id = alert.id
        thread_local.alerter_name = 'recovery_actions'
        thread_local.operation = 'post_receive'
        try:
            begin = datetime.utcnow()
            if alert.status == Status.Closed:
                # Manage Open -> Close transition in status_change method
                return None
            recovery_actions_config = alert.attributes.get(GlobalAttributes.RECOVERY_ACTIONS.var_name, {})
            actions = recovery_actions_config.get(RAConfigFields.ACTIONS.var_name)
            if not actions:
                # If not actions => routing is in charge of invoking alerters
                return
            recovery_actions_data = RecoveryActionData.from_db(alert_id=alert.id)
            app_config = kwargs['config']
            alerters = recovery_actions_config[RAConfigFields.ALERTERS.var_name]
            alerters_always = recovery_actions_config[RAConfigFields.ALERTERS_ALWAYS.var_name]
            current_status = None if recovery_actions_data is None else recovery_actions_data.status
            if current_status is None:
                alert = do_alert(alert, alerters_always, app_config, self.alerter_plugins)
                current_status = RecoveryActionsStatus.InProgress
                provider = recovery_actions_config[RAConfigFields.PROVIDER.var_name]
                recovery_actions_data = RecoveryActionData(alert_id=alert.id, actions=actions,
                                                           provider=provider, status=current_status)
                recovery_actions_data.received_time = begin
                queue = recovery_actions_config[RAConfigFields.TASK_QUEUE.var_name]
                max_retries = recovery_actions_config[RAConfigFields.MAX_RETRIES.var_name]
                action_delay = recovery_actions_config[RAConfigFields.ACTION_DELAY.var_name]
                try:
                    if provider not in self._recovery_actions_providers:
                        raise Exception(f"Recovery action provider '{provider}' not registered")
                    provider_ep = self._recovery_actions_providers[provider]
                    provider_class = f"{provider_ep.module_name}:{provider_ep.attrs[0]}"
                    countdown = self.get_processing_delay(alert, action_delay)
                    logger.info("Scheduled recovery actions to run in %.0f seconds in queue '%s'",
                                countdown, queue)
                    task = launch_actions.apply_async(
                        kwargs=dict(
                            alert_id=alert.id,
                            provider_name=provider,
                            provider_class=provider_class,
                            alerter_plugins={x: f"{y.__module__}:{y.__class__.__name__}"
                                             for x, y in self.alerter_plugins.items()}),
                        countdown=countdown, queue=queue, retry_spec={'max_retries': max_retries})
                    recovery_actions_data.bg_task_id = task.id
                    recovery_actions_data.store(create=True)
                    return alert
                except Exception as e:
                    logger.error("Error preparing recovery actions for alert '%s': %s. Executing alerting", alert.id, e)
                    fill_result(recovery_actions_data, e, begin=begin)
                    recovery_actions_data.store(create=True)
                    alert = do_alert(alert, alerters, app_config, self.alerter_plugins)
                    return alert
            else:
                logger.debug("Recovery actions already in progress. Background tasks in charge")
                return None
        finally:
            thread_local.alerter_name = None
            thread_local.operation = None

    def status_change(self, alert: 'Alert', status: str, text: str, **kwargs) -> Any:
        thread_local.alert_id = alert.id
        thread_local.alerter_name = 'recovery_actions'
        thread_local.operation = 'status_change'
        try:
            current_status = Status(alert.status)
            if status == current_status:
                return None
            if status in (Status.Closed, Status.Expired):
                recovery_actions_data = RecoveryActionData.from_db(alert_id=alert.id)
                ra_status = None if recovery_actions_data is None else recovery_actions_data.status
                if ra_status and ra_status != RecoveryActionsStatus.Finished:
                    recovery_actions_data.status = RecoveryActionsStatus.Finished
                    running_task = recovery_actions_data.bg_task_id
                    if running_task:
                        revoke_task(running_task)
                    if status == Status.Closed:
                        logger.info("Recovered while processing recovery actions. Cancelling alerting")
                        recovery_actions_data.recovery_time = datetime.utcnow()
                    recovery_actions_data.store()
                    return alert, status, text
            return None
        finally:
            thread_local.alerter_name = None
            thread_local.operation = None
