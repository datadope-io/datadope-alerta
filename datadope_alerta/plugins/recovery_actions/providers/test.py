import time
from datetime import datetime, timedelta

from datadope_alerta import DateTime, NormalizedDictView
from . import RecoveryActionsProvider, getLogger, RecoveryActionsResponse, RecoveryActionsResponseStatus
from ... import RetryableException

logger = getLogger(__name__)


class TestProvider(RecoveryActionsProvider):

    def __init__(self, name, app_config):
        super().__init__(name, app_config)

    def get_default_config(self) -> dict:
        return {"oper_id": "ok_5"}

    def execute_actions(self, alert, actions, recovery_actions_config,
                        retry_operation_id=None):
        logger.info("Test RA: Executing actions '%s' for alert '%s'. Current job id: %s", ', '.join(actions), alert.id,
                    retry_operation_id)
        oper_id = NormalizedDictView(recovery_actions_config).get('oper_id', NormalizedDictView(self.config)["oper_id"])
        match oper_id.split('_'):
            case ['ok', sleep]:
                time.sleep(sleep)
                return RecoveryActionsResponse(RecoveryActionsResponseStatus.RESPONSE_OK,
                                               oper_id,
                                               {"data": "ok"},
                                               finish_time=DateTime.make_aware_utc(datetime.now()))
            case ['async', _]:
                time.sleep(1)
                return RecoveryActionsResponse(RecoveryActionsResponseStatus.WAITING_RESPONSE, oper_id)
            case ['retry', status_if_match, mod]:
                m = (int(time.time() * 1000) % int(mod)) == 0
                if m:
                    if status_if_match == 'ok':
                        return RecoveryActionsResponse(RecoveryActionsResponseStatus.RESPONSE_OK,
                                                       oper_id,
                                                       {"data": "ok"})
                    if status_if_match == 'async':
                        return RecoveryActionsResponse(RecoveryActionsResponseStatus.WAITING_RESPONSE, oper_id)
                    if status_if_match == 'error':
                        return RecoveryActionsResponse(RecoveryActionsResponseStatus.RESPONSE_ERROR,
                                                       oper_id,
                                                       {"data": "error"})
                raise RetryableException("Simulated Retryable exception")
            case ['error', sleep]:
                time.sleep(sleep)
                return RecoveryActionsResponse(RecoveryActionsResponseStatus.RESPONSE_ERROR,
                                               oper_id,
                                               {"data": "error"})
            case ['exc', sleep]:
                time.sleep(sleep)
                raise Exception("Simulated Non Retryable exception")
            case _:
                return RecoveryActionsResponse(RecoveryActionsResponseStatus.WAITING_RESPONSE,
                                               oper_id)

    def get_execution_status(self, alert_id, operation_id) -> RecoveryActionsResponse:
        assert operation_id
        _, status, mod = operation_id.split('_')
        mod = int(mod)
        finish = (int(time.time() * 1000) % mod) == 0
        if finish:
            logger.info("Test RA: finished")
            match status:
                case 'ok':
                    return RecoveryActionsResponse(RecoveryActionsResponseStatus.RESPONSE_OK,
                                                   operation_id,
                                                   {"data": "ok"},
                                                   finish_time=DateTime.make_aware_utc(
                                                       datetime.now() - timedelta(seconds=10)))
                case 'fail':
                    return RecoveryActionsResponse(RecoveryActionsResponseStatus.RESPONSE_ERROR,
                                                   operation_id,
                                                   {"data": "error"})

        logger.info("Test RA: not finished")
        return RecoveryActionsResponse(RecoveryActionsResponseStatus.WAITING_RESPONSE,
                                       operation_id)
