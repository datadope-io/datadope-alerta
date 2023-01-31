import os
from datetime import datetime

from pkg_resources import iter_entry_points
from typing import Optional, Any

from alerta.models.alert import Alert
from alerta.models.enums import Status
from alerta.plugins import PluginBase

from iometrics_alerta import DateTime, ConfigKeyDict, ContextualConfiguration as CConfig, safe_convert, \
    VarDefinition
from iometrics_alerta import get_hierarchical_configuration
from iometrics_alerta import GlobalAttributes, RecoveryActionsStatus
from iometrics_alerta import RecoveryActionsDataFields as RADataFields
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
        recovery_actions_key = GlobalAttributes.RECOVERY_ACTIONS.var_name
        normalized_key = ConfigKeyDict.key_transform(recovery_actions_key)

        # Configuration from config file
        app_config = ConfigKeyDict(kwargs['config'])
        if normalized_key in app_config:
            ra_global_config = ConfigKeyDict(safe_convert(app_config[normalized_key], dict))
        else:
            ra_global_config = ConfigKeyDict()
            for key, value in app_config.items():
                if key.startswith(normalized_key):
                    ra_global_config[key[len(normalized_key):]] = value

        # Configuration from environment
        env_config = ConfigKeyDict(os.environ)
        if normalized_key in app_config:
            ra_env_config = ConfigKeyDict(safe_convert(env_config[normalized_key], dict))
        else:
            ra_env_config = ConfigKeyDict()
            for key, value in env_config.items():
                if key.startswith(normalized_key):
                    ra_env_config[key[len(normalized_key):]] = value

        # Configuration from alert
        alert_attributes = ConfigKeyDict(alert.attributes)
        ra_alert_config = ConfigKeyDict(safe_convert(
            alert_attributes.get(recovery_actions_key, {}), dict))
        original_key = alert_attributes.original_key(recovery_actions_key)
        if original_key and original_key != recovery_actions_key:
            alert.attributes.pop(original_key, None)

        ordered_configs = [ra_alert_config, ra_env_config, ra_global_config]

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
            alert.attributes[recovery_actions_key] = recovery_actions_config
        return alert

    def take_action(self, alert: 'Alert', action: str, text: str, **kwargs) -> Any:
        pass

    def take_note(self, alert: 'Alert', text: Optional[str], **kwargs) -> Any:
        pass

    def delete(self, alert: 'Alert', **kwargs) -> bool:
        return True

    def post_receive(self, alert: 'Alert', **kwargs) -> Optional['Alert']:
        begin = datetime.now()
        if alert.status == Status.Closed:
            # Manage Open -> Close transition in status_change method
            return None
        recovery_actions_config = alert.attributes.get(GlobalAttributes.RECOVERY_ACTIONS.var_name, {})
        actions = recovery_actions_config.get(RAConfigFields.ACTIONS.var_name)
        if not actions:
            # If not actions => routing is in charge of invoking alerters
            return
        recovery_actions_data = alert.attributes.setdefault(RADataFields.ATTRIBUTE, {})
        app_config = kwargs['config']
        alerters = recovery_actions_config[RAConfigFields.ALERTERS.var_name]
        alerters_always = recovery_actions_config[RAConfigFields.ALERTERS_ALWAYS.var_name]
        current_status = recovery_actions_data.get(RADataFields.FIELD_STATUS)
        if current_status is None:
            alert = do_alert(alert, alerters_always, app_config, self.alerter_plugins)
            current_status = RecoveryActionsStatus.InProgress
            recovery_actions_data[RADataFields.FIELD_STATUS] = current_status.value
            recovery_actions_data[RADataFields.FIELD_RECEIVED] = DateTime.iso8601_utc(begin)
            provider = recovery_actions_config[RAConfigFields.PROVIDER.var_name]
            queue = recovery_actions_config[RAConfigFields.TASK_QUEUE.var_name]
            max_retries = recovery_actions_config[RAConfigFields.MAX_RETRIES.var_name]
            action_delay = recovery_actions_config[RAConfigFields.ACTION_DELAY.var_name]
            try:
                if provider not in self._recovery_actions_providers:
                    raise Exception(f"Recovery action provider '{provider}' not registered")
                provider_ep = self._recovery_actions_providers[provider]
                provider_class = f"{provider_ep.module_name}:{provider_ep.attrs[0]}"
                countdown = self.get_processing_delay(alert, action_delay)
                logger.info("Scheduled recovery actions for alert '%s' to run in %.0f seconds in queue '%s'",
                            alert.id, countdown, queue)
                task = launch_actions.apply_async(
                    kwargs=dict(
                        alert_id=alert.id,
                        provider_name=provider,
                        provider_class=provider_class,
                        alerter_plugins={x: f"{y.__module__}:{y.__class__.__name__}"
                                         for x, y in self.alerter_plugins.items()}),
                    countdown=countdown, queue=queue, retry_spec={'max_retries': max_retries})
                recovery_actions_data[RADataFields.FIELD_BG_TASK_ID] = task.id
                alert.attributes = alert.update_attributes({RADataFields.ATTRIBUTE: recovery_actions_data})
                return alert
            except Exception as e:
                logger.error("Error preparing recovery actions for alert '%s': %s. Executing alerting", alert.id, e)
                fill_result(recovery_actions_data, e, begin=begin)
                alert.attributes = alert.update_attributes({RADataFields.ATTRIBUTE: recovery_actions_data})
                alert = do_alert(alert, alerters, app_config, self.alerter_plugins)
                return alert
        else:
            logger.debug("Recovery actions for alert '%s' already in progress. Background tasks in charge",
                         alert.id)
            return None

    def status_change(self, alert: 'Alert', status: str, text: str, **kwargs) -> Any:
        current_status = Status(alert.status)
        if status == current_status:
            return None
        if status in (Status.Closed, Status.Expired):
            recovery_actions_data = alert.attributes.get(RADataFields.ATTRIBUTE, {})
            ra_status = recovery_actions_data.get(RADataFields.FIELD_STATUS)
            if ra_status and ra_status != RecoveryActionsStatus.Finished:
                recovery_actions_data[RADataFields.FIELD_STATUS] = RecoveryActionsStatus.Finished.value
                running_task = recovery_actions_data.get(RADataFields.FIELD_BG_TASK_ID)
                if running_task:
                    revoke_task(running_task)
                if status == Status.Closed:
                    logger.info("Alert '%s' recovered while processing recovey actions. Cancelling alerting",
                                alert.id)
                    recovery_actions_data[RADataFields.FIELD_RECOVERED_AT] = DateTime.iso8601_utc(datetime.now())
                return alert, status, text
        return None
