from typing import List, Any, Optional, Dict

from datadope_alerta import thread_local
from datadope_alerta.backend.flexiblededup.models.rules import ContextualRule
from datadope_alerta.plugins import getLogger
from datadope_alerta.plugins.notifier.utils import compare_conditions
from alerta.utils.collections import merge

from alerta.models.alert import Alert
from alerta.plugins import PluginBase
from alerta.utils.format import DateTime

logger = getLogger(__name__)


class NotifierPlugin(PluginBase):

    def __init__(self, name=None):
        super().__init__(name=name)

    @staticmethod
    def compare(source: Alert, conditions: List[ContextualRule]) -> Dict:
        return compare_conditions(source.serialize, conditions)

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
            logger.debug("PREPROCESSING ALERT")
            conditions = self.get_conditions(page=kwargs.get('page', 100))
            context = self.compare(alert, conditions)
            for key, value in context.items():
                if value is not None and key in ('create_time', 'receive_time', 'last_receive_time'):
                    value = DateTime.parse(value)
                try:
                    original = getattr(alert, key)
                    if value is None or original is None:
                        setattr(alert, key, value)
                    elif type(value) == type(original):
                        if isinstance(value, dict):
                            merge(original, value)
                        elif isinstance(value, list):
                            original.extend([v for v in value if v not in original])
                        else:
                            setattr(alert, key, value)
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
