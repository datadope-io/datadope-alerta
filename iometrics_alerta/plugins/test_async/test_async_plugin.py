import time
from typing import Any, Dict, Tuple, Optional

from alerta.models.alert import Alert

from iometrics_alerta.plugins import getLogger, RetryableException, VarDefinition
from iometrics_alerta.plugins.iom_plugin import Alerter, IOMAlerterPlugin


logger = getLogger(__name__)


class TestAlerter(Alerter):

    def process_event(self, alert: Alert, reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        op = 'process_event'
        try:
            index, _ = self.get_contextual_configuration(VarDefinition('INDEX', default=0), alert, op)
            sleep, _ = self.get_contextual_configuration(VarDefinition('SLEEP', default=0.0), alert, op)
            time.sleep(sleep)
            if index == 1:
                raise Exception('Simulating an exception')
            elif index == 2:
                raise RetryableException('Simulating a retryable exception')
            elif index == 3:
                return False, self.failure_response('error_for_test', 'message from the error', 'extra_info')
            elif index == 4:
                return False, self.failure_response('error_for_test', 'message from the error', {"field": "value"})
            elif index == 5:
                try:
                    raise Exception('The exception')
                except Exception as exc:
                    return False, self.failure_response('error_for_test', 'message from the error', exc)
            return True, {'test': 'ok'}
        finally:
            logger.info("Test: End event")

    def process_recovery(self, alert: Alert, reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        op = 'process_recovery'
        try:
            index, _ = self.get_contextual_configuration(VarDefinition('INDEX', default=0), alert, op)
            sleep, _ = self.get_contextual_configuration(VarDefinition('SLEEP', default=0.0), alert, op)
            time.sleep(sleep)
            if index == 1:
                raise Exception('Simulating an exception')
            elif index == 2:
                raise RetryableException('Simulating a retryable exception')
            elif index == 3:
                return False, self.failure_response('error_for_test', 'message from the error', 'extra_info')
            elif index == 4:
                return False, self.failure_response('error_for_test', 'message from the error', {"field": "value"})
            elif index == 5:
                try:
                    raise Exception('The exception')
                except Exception as exc:
                    return False, self.failure_response('error_for_test', 'message from the error', exc)
            return True, {'test_recovery': 'ok', 'reason': reason}
        finally:
            logger.info("Test: End recovery")


class TestPlugin(IOMAlerterPlugin):

    def get_alerter_default_configuration(self) -> dict:
        return {
            'sleep': {
                'new': 10.0,
                'recovery': 3.0
            },
            'index': '{"new": 0, "recovery": 0}'
        }

    def get_alerter_class(self):
        return TestAlerter
