from datetime import datetime, timedelta
from typing import Optional, Any

import pytz

from alerta.models.alert import Alert
from alerta.models.enums import Action, Status
from alerta.plugins import PluginBase

from datadope_alerta import GlobalAttributes as GAttr, ContextualConfiguration as CConfig, DateTime, thread_local
from datadope_alerta import NormalizedDictView, safe_convert
from datadope_alerta.backend.flexiblededup.models.alerters import AlerterOperationData
from datadope_alerta.plugins import getLogger, AlerterStatus

logger = getLogger(__name__)


class IOMAPreprocessPlugin(PluginBase):

    def __init__(self, name=None):
        super().__init__(name=name)
        self.__resolve_action_name = None

    @property
    def resolve_action_name(self):
        if not self.__resolve_action_name:
            self.__resolve_action_name = CConfig.get_global_configuration(GAttr.CONDITION_RESOLVED_ACTION_NAME)
        return self.__resolve_action_name

    @staticmethod
    def adapt_event_tags(alert_attributes: NormalizedDictView):
        event_tags_key = GAttr.EVENT_TAGS.var_name
        if event_tags_key in alert_attributes:
            event_tags = safe_convert(alert_attributes[event_tags_key], dict)
            alert_attributes[event_tags_key] = event_tags

    @staticmethod
    def adapt_alerters(alert, alert_attributes: NormalizedDictView, config):
        alerters_key = GAttr.ALERTERS.var_name
        alerters = CConfig.get_global_attribute_value(GAttr.ALERTERS, alert, global_config=config)
        if alerters is not None:
            alert_attributes[alerters_key] = alerters

    @staticmethod
    def adapt_auto_close(alert, alert_attributes, config):
        # Prepare auto close properties
        auto_close_after = CConfig.get_global_attribute_value(GAttr.AUTO_CLOSE_AFTER, alert=alert,
                                                              global_config=config)
        close_at_key = GAttr.AUTO_CLOSE_AT.var_name
        if auto_close_after:
            rec_dt = alert.last_receive_time or alert.receive_time
            if rec_dt:
                rec_dt = pytz.utc.localize(rec_dt)
            else:
                rec_dt = datetime.now().astimezone(pytz.utc)
            alert_attributes[close_at_key] = rec_dt + timedelta(seconds=auto_close_after)
        if close_at_key in alert_attributes:
            close_at = alert_attributes[close_at_key]
            if not isinstance(close_at, datetime):
                try:
                    alert_attributes[close_at_key] = DateTime.parse(str(close_at))
                except ValueError as e:
                    logger.warning("Cannot parse '%s' to datetime for attribute '%s' in alert '%s': %s",
                                   close_at, close_at_key, alert.id, e)

    @staticmethod
    def adapt_recovery_actions(alert, alert_attributes, config):
        # TODO: Adjust Zabbix task to new recoveryAction Attribute
        #
        # limit = tags[HOST.HOST]
        # extra_vars = {x[prefix_len:]: y for x, y in iteritems(tags) if x.startswith(TAG_AWX_EXTRAVARS_PREFIX)}
        # extra_tags = {x: y for x, y in iteritems(tags) if not x.startswith(TAG_AWX_EXTRAVARS_PREFIX)
        #               and x != TAG_AWX_RECOVERY_ACTION and x != TAG_AWX_INFO_ACTION}

        pass

    def pre_receive(self, alert: 'Alert', **kwargs) -> 'Alert':
        thread_local.alert_id = alert.id
        thread_local.alerter_name = 'iom_preprocess'
        try:
            logger.debug("PREPROCESSING ALERT FOR IOMETRICS")
            # Ensure eventTags is a dict
            alert_attributes = NormalizedDictView(alert.attributes)
            config = kwargs['config']
            self.adapt_event_tags(alert_attributes)
            self.adapt_alerters(alert, alert_attributes, config)
            self.adapt_auto_close(alert, alert_attributes, config)
            self.adapt_recovery_actions(alert, alert_attributes, config)
            return alert
        finally:
            thread_local.alerter_name = None

    def post_receive(self, alert: 'Alert', **kwargs) -> Optional['Alert']:
        return None

    def status_change(self, alert: 'Alert', status: str, text: str, **kwargs) -> Any:
        return None

    def take_action(self, alert: 'Alert', action: str, text: str, **kwargs) -> Any:
        """
        Manage Condition Resolved iometrics custom action and reopen alert
        """
        thread_local.alert_id = alert.id
        thread_local.alerter_name = 'iom_preprocess'
        thread_local.operation = action
        try:
            resolve_action_name = self.resolve_action_name
            if action == resolve_action_name:
                must_close = CConfig.get_global_attribute_value(GAttr.CONDITION_RESOLVED_MUST_CLOSE,
                                                                alert=alert)
                alert.tags.append(CConfig.get_global_configuration(GAttr.CONDITION_RESOLVED_TAG))
                alert.update_tags(alert.tags)  # FIXME: Needed until bug in main plugin loop is solved
                if must_close:
                    logger.info("Closing alert on a resolve action as '%s' tag is active",
                                GAttr.CONDITION_RESOLVED_MUST_CLOSE.var_name)
                    return alert, Action.CLOSE, text, kwargs.get('timeout')
            elif action == Action.OPEN and alert.status == Status.Closed:
                logger.warning("Reopening alert. Removing alerter information")
                AlerterStatus.clear(alert_id=alert.id)
                AlerterOperationData.clear(alert_id=alert.id)
                condition_resolved_tag = CConfig.get_global_configuration(GAttr.CONDITION_RESOLVED_TAG)
                if condition_resolved_tag in alert.tags:
                    alert.tags.remove(condition_resolved_tag)
                    alert.update_tags(alert.tags)
                    return alert, action, text, kwargs.get('timeout')
            return None
        finally:
            thread_local.alerter_name = None
            thread_local.operation = None

    def take_note(self, alert: 'Alert', text: Optional[str], **kwargs) -> Any:
        return None

    def delete(self, alert: 'Alert', **kwargs) -> bool:
        return True
