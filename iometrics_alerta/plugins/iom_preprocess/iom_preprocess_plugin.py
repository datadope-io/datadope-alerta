from datetime import datetime, timedelta
from typing import Optional, Any

import pytz

from alerta.models.alert import Alert
from alerta.plugins import PluginBase

from iometrics_alerta import GlobalAttributes as GAttr, ContextualConfiguration as CConfig, DateTime
from iometrics_alerta import ConfigKeyDict, safe_convert
from iometrics_alerta.plugins import getLogger

logger = getLogger(__name__)


class IOMAPreprocessPlugin(PluginBase):

    @staticmethod
    def adapt_event_tags(alert, alert_attributes):
        event_tags_key = GAttr.EVENT_TAGS.var_name
        if event_tags_key in alert_attributes:
            event_tags = safe_convert(alert_attributes[event_tags_key], dict)
            alert.attributes[event_tags_key] = event_tags
            alert_attributes[event_tags_key] = event_tags
            original_key = alert_attributes.original_key(event_tags_key)
            if original_key and original_key != event_tags_key:
                alert.attributes.pop(original_key, None)

    @staticmethod
    def adapt_alerters(alert, alert_attributes, config):
        alerters_key = GAttr.ALERTERS.var_name
        alerters = CConfig.get_global_attribute_value(GAttr.ALERTERS, alert, global_config=config)
        if alerters is not None:
            original_key = alert_attributes.original_key(alerters_key)
            if original_key and original_key != alerters_key:
                alert.attributes.pop(original_key)
            alert.attributes[alerters_key] = alerters
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
            alert.attributes[close_at_key] = rec_dt + timedelta(seconds=auto_close_after)
            alert_attributes[close_at_key] = alert.attributes[close_at_key]
        if close_at_key in alert_attributes:
            close_at = alert_attributes[close_at_key]
            original_key = alert_attributes.original_key(close_at_key)
            if not isinstance(close_at, datetime):
                try:
                    alert.attributes[close_at_key] = DateTime.parse(str(close_at))
                    alert_attributes[close_at_key] = alert.attributes[close_at_key]
                except ValueError as e:
                    logger.warning("Cannot parse '%s' to datetime for attribute '%s' in alert '%s': %s",
                                   close_at, close_at_key, alert.id, e)
                    close_at_key = ''
            if original_key and original_key != close_at_key:
                alert.attributes.pop(original_key, None)

    @staticmethod
    def adapt_recovery_actions(alert, alert_attributes, config):
        # TODO: Adjust Zabbix task a new recoveryAction Attribute
        #
        # limit = tags[HOST.HOST]
        # extra_vars = {x[prefix_len:]: y for x, y in iteritems(tags) if x.startswith(TAG_AWX_EXTRAVARS_PREFIX)}
        # extra_tags = {x: y for x, y in iteritems(tags) if not x.startswith(TAG_AWX_EXTRAVARS_PREFIX)
        #               and x != TAG_AWX_RECOVERY_ACTION and x != TAG_AWX_INFO_ACTION}

        pass

    def pre_receive(self, alert: 'Alert', **kwargs) -> 'Alert':
        logger.debug("PREPROCESSING ALERT FOR IOMETRICS")
        # Ensure eventTags is a dict
        alert_attributes = ConfigKeyDict(alert.attributes)
        config = kwargs['config']
        self.adapt_event_tags(alert, alert_attributes)
        self.adapt_alerters(alert, alert_attributes, config)
        self.adapt_auto_close(alert, alert_attributes, config)
        self.adapt_recovery_actions(alert, alert_attributes, config)
        return alert

    def post_receive(self, alert: 'Alert', **kwargs) -> Optional['Alert']:
        return None

    def status_change(self, alert: 'Alert', status: str, text: str, **kwargs) -> Any:
        return None

    def take_action(self, alert: 'Alert', action: str, text: str, **kwargs) -> Any:
        return None

    def take_note(self, alert: 'Alert', text: Optional[str], **kwargs) -> Any:
        return None

    def delete(self, alert: 'Alert', **kwargs) -> bool:
        return True
