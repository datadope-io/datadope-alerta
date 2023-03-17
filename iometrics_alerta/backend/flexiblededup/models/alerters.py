from datetime import datetime
from typing import Optional


class AlerterOperationData:
    __db = None

    FIELD_TASK_CHAIN_INFO_TEXT = 'text'
    FIELD_TASK_CHAIN_INFO_TASK_DEF = 'task_def'
    FIELD_TASK_CHAIN_INFO_ACTION = 'action'

    @classmethod
    def get_db(cls):
        if cls.__db is None:
            from ..specific import SpecificBackend
            cls.__db = SpecificBackend.instance
        return cls.__db

    def __init__(self, alert_id, alerter, operation, **kwargs):
        self.alert_id: str = alert_id
        self.alerter: str = alerter
        self.operation: str = operation
        self.id: Optional[str] = kwargs.get('id')
        self.received_time: Optional[datetime] = kwargs.get('received_time')
        self.start_time: Optional[datetime] = kwargs.get('start_time')
        self.end_time: Optional[datetime] = kwargs.get('end_time')
        self.success: bool = kwargs.get('success', False)
        self.skipped: bool = kwargs.get('skipped', False)
        self.retries: int = kwargs.get('retries', 0)
        self.response: Optional[dict] = kwargs.get('response')
        self.reason: Optional[str] = kwargs.get('reason')
        self.bg_task_id: Optional[str] = kwargs.get('bg_task_id')
        self.task_chain_info: Optional[dict] = kwargs.get('task_chain_info')

    @classmethod
    def from_db(cls, alert_id, alerter, operation, create_default=True) -> Optional['AlerterOperationData']:
        alerter_data = cls.get_db().get_alerter_data(alert_id, alerter, operation)
        if alerter_data is None and create_default:
            alerter_data = AlerterOperationData(alert_id=alert_id, alerter=alerter, operation=operation)
        return alerter_data

    @classmethod
    def from_record(cls, rec) -> 'AlerterOperationData':
        return AlerterOperationData(
            id=rec.id,
            alert_id=rec.alert_id,
            alerter=rec.alerter,
            operation=rec.operation,
            received_time=rec.received_time,
            start_time=rec.start_time,
            end_time=rec.end_time,
            success=rec.success,
            skipped=rec.skipped,
            retries=rec.retries,
            response=rec.response,
            reason=rec.reason,
            bg_task_id=rec.bg_task_id,
            task_chain_info=rec.task_chain_info
        )

    @classmethod
    def has_alerting_succeeded(cls, alert_id, alerter) -> bool:
        data = cls.from_db(alert_id, alerter, 'new', create_default=False)
        return (data is not None) and (data.success is True)

    @classmethod
    def last_executing_operation(cls, alert_id, alerter) -> Optional['AlerterOperationData']:
        return cls.get_db().get_last_executing_operation(alert_id, alerter)

    def store(self):
        if self.id is None:
            return self.get_db().create_alerter_data(self)
        else:
            return self.get_db().update_alerter_data(self)

    @classmethod
    def clear(cls, alert_id):
        cls.get_db().clear_alerters_data(alert_id)
