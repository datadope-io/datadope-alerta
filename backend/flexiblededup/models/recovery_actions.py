from datetime import datetime
from enum import Enum
from typing import Optional, List


class RecoveryActionsStatus(str, Enum):
    InProgress = 'in_progress'
    WaitingResolution = 'waiting'
    Finished = 'finished'


class RecoveryActionData:
    __db = None

    @classmethod
    def get_db(cls):
        if cls.__db is None:
            from ..specific import SpecificBackend
            cls.__db = SpecificBackend.instance
        return cls.__db

    def __init__(self, alert_id, provider, actions: List[str], status: RecoveryActionsStatus, **kwargs):
        self.alert_id: str = alert_id
        self.provider: str = provider
        self.actions: List[str] = actions
        self.status: RecoveryActionsStatus = status
        self.received_time: Optional[datetime] = kwargs.get('received_time')
        self.start_time: Optional[datetime] = kwargs.get('start_time')
        self.end_time: Optional[datetime] = kwargs.get('end_time')
        self.recovery_time: Optional[datetime] = kwargs.get('recovery_time')
        self.alerting_time: Optional[datetime] = kwargs.get('alerting_time')
        self.success: bool = kwargs.get('success', False)
        self.retries: Optional[int] = kwargs.get('retries')
        self.response: Optional[dict] = kwargs.get('response')
        self.job_id: Optional[str] = kwargs.get('job_id')
        self.bg_task_id: Optional[str] = kwargs.get('bg_task_id')

    @classmethod
    def from_db(cls, alert_id) -> Optional['RecoveryActionData']:
        return cls.get_db().get_recovery_action_data(alert_id)

    @classmethod
    def from_record(cls, rec) -> 'RecoveryActionData':
        return RecoveryActionData(
            alert_id=rec.alert_id,
            provider=rec.provider,
            actions=rec.actions,
            status=RecoveryActionsStatus(rec.status),
            received_time=rec.received_time,
            start_time=rec.start_time,
            end_time=rec.end_time,
            recovery_time=rec.recovery_time,
            alerting_time=rec.alerting_time,
            success=rec.success,
            retries=rec.retries,
            response=rec.response,
            job_id=rec.job_id,
            bg_task_id=rec.bg_task_id
        )

    def store(self, create=False):
        if create:
            return self.get_db().create_recovery_action_data(self)
        else:
            return self.get_db().update_recovery_action_data(self)
