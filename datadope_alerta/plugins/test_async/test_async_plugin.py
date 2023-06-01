import time
from typing import Any, Dict, Tuple, Optional

from alerta.models.alert import Alert

from datadope_alerta.plugins import getLogger, RetryableException, VarDefinition
from datadope_alerta.plugins.iom_plugin import Alerter, IOMAlerterPlugin


logger = getLogger(__name__)


class TestAlerter(Alerter):

    def _do_process(self, alert, op):
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
        elif index == 6 and self.bgtask:
            retries = self.bgtask.request.retries
            if (retries % 3) != 2:
                raise RetryableException('Simulating a retryable exception')

    @classmethod
    def get_default_configuration(cls) -> dict:
        return {
            'sleep': {
                'new': 10.0,
                'recovery': 3.0
            },
            'index': {"new": 0, "recovery": 0}
        }

    def process_event(self, alert: Alert, reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        op = 'process_event'
        try:
            self._do_process(alert, op)
            return True, {'test': 'ok'}
        finally:
            logger.info("Test: End event")

    def process_recovery(self, alert: Alert, reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        op = 'process_recovery'
        try:
            self._do_process(alert, op)
            return True, {'test_recovery': 'ok', 'reason': reason}
        finally:
            logger.info("Test: End recovery")

    def process_repeat(self, alert: 'Alert', reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        op = 'process_repeat'
        try:
            self._do_process(alert, op)
            return True, {'test_repeat': 'ok', 'reason': reason}
        finally:
            logger.info("Test: End Repeat")

    def process_action(self, alert: 'Alert', reason: Optional[str], action: str) -> Tuple[bool, Dict[str, Any]]:
        return super().process_action(alert, reason, action)


class TestPlugin(IOMAlerterPlugin):

    def get_alerter_class(self):
        return TestAlerter
