from typing import Optional

from .models.alerters import AlerterOperationData
from .models.recovery_actions import RecoveryActionData
from alerta.database.backends.postgres.base import Backend


# noinspection PyProtectedMember
class SpecificBackend:
    instance: 'SpecificBackend' = None

    def __new__(cls, *args, **kwargs):
        instance = super().__new__(cls)
        cls.instance = instance
        return instance

    def __init__(self, db_backend: Backend):
        self.backend = db_backend

    # Alerters Status

    def get_status(self, alert_id: str, alerter: str) -> Optional[str]:
        query = """
            SELECT status 
              FROM alerter_status 
             WHERE alert_id=%(alert_id)s
               AND alerter=%(alerter)s
        """
        record = self.backend._fetchone(query, dict(alert_id=alert_id, alerter=alerter))
        return record.status if record else None

    def create_status(self, alert_id: str, alerter: str, status: str) -> Optional[str]:
        insert = """
            INSERT INTO alerter_status (alert_id, alerter, status)
            VALUES (%(alert_id)s, %(alerter)s, %(status)s)
            RETURNING *
        """
        record = self.backend._insert(insert, dict(alert_id=alert_id, alerter=alerter, status=status))
        return record.status if record else None

    def update_status(self, alert_id: str, alerter: str, status: str) -> Optional[str]:
        update = """
            UPDATE alerter_status 
               SET status=%(status)s
             WHERE alert_id=%(alert_id)s
               AND alerter=%(alerter)s
             RETURNING *
        """
        record = self.backend._updateone(update, dict(alert_id=alert_id, alerter=alerter, status=status),
                                         returning=True)
        return record.status if record else None

    # Alerters Data

    def get_alerter_data(self, alert_id: str, alerter: str, operation: str) -> Optional[AlerterOperationData]:
        query = """
            SELECT *
              FROM alerter_data
             WHERE alert_id=%(alert_id)s
               AND alerter=%(alerter)s
               AND operation=%(operation)s
             ORDER BY received_time DESC
             LIMIT 1
        """
        record = self.backend._fetchone(query, dict(alert_id=alert_id, alerter=alerter, operation=operation))
        return AlerterOperationData.from_record(record) if record else None

    def create_alerter_data(self, alerter_data: AlerterOperationData) -> Optional[AlerterOperationData]:
        insert = """
            INSERT INTO alerter_data (alert_id, alerter, operation, received_time, start_time, end_time, 
                success, skipped, retries, response, reason, bg_task_id, task_chain_info)
            VALUES (%(alert_id)s, %(alerter)s, %(operation)s, %(received_time)s, %(start_time)s, %(end_time)s, 
                %(success)s, %(skipped)s, %(retries)s, %(response)s, %(reason)s, %(bg_task_id)s,
                %(task_chain_info)s)
            RETURNING *
        """
        record = self.backend._insert(insert, vars(alerter_data))
        return AlerterOperationData.from_record(record) if record else None

    def update_alerter_data(self, alerter_data: AlerterOperationData) -> Optional[AlerterOperationData]:
        update = """
            UPDATE alerter_data
               SET alert_id=%(alert_id)s, alerter=%(alerter)s, operation=%(operation)s, 
                   received_time=%(received_time)s, start_time=%(start_time)s, end_time=%(end_time)s, 
                   success=%(success)s, skipped=%(skipped)s, retries=%(retries)s, response=%(response)s, 
                   reason=%(reason)s, bg_task_id=%(bg_task_id)s, task_chain_info=%(task_chain_info)s
             WHERE id=%(id)s
         RETURNING *
        """
        record = self.backend._updateone(update, vars(alerter_data), returning=True)
        return AlerterOperationData.from_record(record) if record else None

    # Recovery actions

    def get_recovery_action_data(self, alert_id: str) -> Optional[RecoveryActionData]:
        query = """
            SELECT *
              FROM recovery_action_data
             WHERE alert_id=%(alert_id)s
        """
        record = self.backend._fetchone(query, dict(alert_id=alert_id))
        return RecoveryActionData.from_record(record) if record else None

    def create_recovery_action_data(self, recovery_action_data: RecoveryActionData) -> Optional[RecoveryActionData]:
        insert = """
            INSERT INTO recovery_action_data (alert_id, provider, actions, status, received_time, start_time, 
                end_time, recovery_time, alerting_time, success, retries, response, 
                job_id, bg_task_id
                )
            VALUES (%(alert_id)s, %(provider)s, %(actions)s, %(status)s, %(received_time)s, %(start_time)s, 
                %(end_time)s, %(recovery_time)s, %(alerting_time)s, %(success)s, %(retries)s, %(response)s, 
                %(job_id)s, %(bg_task_id)s
                )
            RETURNING *
        """
        record = self.backend._insert(insert, vars(recovery_action_data))
        return RecoveryActionData.from_record(record) if record else None

    def update_recovery_action_data(self, recovery_action_data: RecoveryActionData) -> Optional[RecoveryActionData]:
        update = """
            UPDATE recovery_action_data
               SET alert_id=%(alert_id)s, provider=%(provider)s, actions=%(actions)s, status=%(status)s, 
                   received_time=%(received_time)s, start_time=%(start_time)s, end_time=%(end_time)s, 
                   recovery_time=%(recovery_time)s, alerting_time=%(alerting_time)s, success=%(success)s, 
                   retries=%(retries)s, response=%(response)s, job_id=%(job_id)s, bg_task_id=%(bg_task_id)s
             WHERE alert_id=%(alert_id)s 
         RETURNING *
        """
        record = self.backend._updateone(update, vars(recovery_action_data), returning=True)
        return RecoveryActionData.from_record(record) if record else None
