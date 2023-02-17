import time
from typing import Any, Dict, Tuple, Optional

from alerta.models.alert import Alert

from iometrics_alerta.plugins import getLogger
from iometrics_alerta.plugins.iom_plugin import Alerter, IOMSyncAlerterPlugin


logger = getLogger(__name__)


class TestAlerter(Alerter):
    invocation = 0

    def get_default_configuration(self) -> dict:
        return {}

    def process_event(self, alert: Alert, reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        try:
            time.sleep(5)
            logger.info("Test: End event")
            index = TestAlerter.invocation % 5
            if index == 1:
                raise Exception('Simulating an exception')
            elif index == 2:
                return False, self.failure_response('error_for_test', 'message from the error', 'extra_info')
            elif index == 3:
                return False, self.failure_response('error_for_test', 'message from the error', {"field": "value"})
            elif index == 4:
                try:
                    raise Exception('The exception')
                except Exception as exc:
                    return False, self.failure_response('error_for_test', 'message from the error', exc)
            return True, {'test': 'ok'}
        finally:
            TestAlerter.invocation += 1

    def process_recovery(self, alert: Alert, reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        time.sleep(3)
        logger.info("Test: End recovery")
        return True, {'test_recovery': 'ok'}

    def process_repeat(self, alert: 'Alert', reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        return True, {}


class TestPlugin(IOMSyncAlerterPlugin):

    def get_alerter_class(self):
        return TestAlerter
