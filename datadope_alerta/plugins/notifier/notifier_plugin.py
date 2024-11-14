from copy import deepcopy
from typing import List, Any, Optional, Dict

from datadope_alerta import thread_local
from datadope_alerta.backend.flexiblededup.models.rules import ContextualRule
from datadope_alerta.plugins import getLogger
from datadope_alerta.plugins.notifier.utils import compare_conditions

from alerta.models.alert import Alert
from alerta.plugins import PluginBase
from alerta.utils.format import DateTime

logger = getLogger(__name__)


class NotifierPlugin(PluginBase):

    ATTRIBUTES_CONVERSION_NAMES = {
        'type': 'event_type',
        'createTime': 'create_time',
        'rawData': 'raw_data',
        'duplicateCount': 'duplicate_count',
        'previousSeverity': 'previous_severity',
        'trendIndication': 'trend_indication',
        'receiveTime': 'receive_time',
        'lastReceiveId': 'last_receive_id',
        'lastReceiveTime': 'last_receive_time',
        'updateTime': 'update_time',
    }
    ATTRIBUTES_TO_IGNORE = ['id', 'href', 'history', 'last_receive_id']
    DATE_ATTRIBUTES = ['createTime', 'receiveTime', 'lastReceiveTime', 'updateTime']

    def __init__(self, name=None):
        super().__init__(name=name)

    @staticmethod
    def compare(source: Alert, conditions: List[ContextualRule]) -> Dict:
        return compare_conditions(deepcopy(source.serialize), conditions)

    @staticmethod
    def get_conditions(page) -> List[ContextualRule]:
        offset = 0
        all_rules = []
        reached = False

        while not reached:
            rules = ContextualRule.all_from_db(limit=page, offset=offset)
            all_rules.extend(rules)
            offset += page

            if not rules or len(rules) < page:
                reached = True

        return all_rules

    def pre_receive(self, alert: 'Alert', **kwargs) -> 'Alert':
        thread_local.alert_id = alert.id
        thread_local.alerter_name = 'notifier'
        try:
            conditions = self.get_conditions(page=kwargs.get('page', 100))
            if not conditions:
                logger.debug("NO CONDITIONS FOUND")
                return alert
            logger.debug("CHECKING CONDITIONS")
            final_alert_serialized = self.compare(alert, conditions)
            for key, value in final_alert_serialized.items():
                if key in self.ATTRIBUTES_TO_IGNORE:
                    continue
                attr_name = self.ATTRIBUTES_CONVERSION_NAMES.get(key, key)
                if value is not None and key in self.DATE_ATTRIBUTES and isinstance(value, str):
                    value = DateTime.parse(value)
                try:
                    original = getattr(alert, attr_name)
                    if original == value:
                        continue
                    if value is None or original is None or type(value) == type(original):
                        setattr(alert, attr_name, value)
                    else:
                        logger.warning("Context key '%s' has a wrong type '%s' and should be '%s'. Ignoring",
                                       key, type(value).__name__, type(original).__name__)
                except AttributeError:
                    logger.warning("Attribute '%s' not found in alert object. Ignoring", key)
            return alert
        finally:
            thread_local.alerter_name = None

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
