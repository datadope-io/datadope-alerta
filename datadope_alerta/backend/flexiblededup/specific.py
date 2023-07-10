from typing import Optional

from alerta.database.backends.postgres.base import Backend
from .models.alert_dependency import AlertDependency
from .models.alerters import AlerterOperationData
from .models.key_value_store import KeyValueParameter
from .models.recovery_actions import RecoveryActionData
from .models.rules import ContextualRule


# noinspection PyProtectedMember
class SpecificBackend:
    instance: 'SpecificBackend' = None

    def __new__(cls, *args, **kwargs):
        instance = super().__new__(cls)
        cls.instance = instance
        return instance

    def __init__(self, db_backend: Backend):
        self.backend = db_backend

    # ---------------------
    # Alerters Status
    # ---------------------

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

    def clear_status(self, alert_id: str):
        delete = """
            DELETE FROM alerter_status
             WHERE alert_id=%(alert_id)s
        """
        self.backend._deleteall(delete, dict(alert_id=alert_id))

    # -----------------------
    # Alerters Data
    # -----------------------

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
            ON CONFLICT (alert_id, alerter, operation) WHERE operation in ('new', 'recovery') DO UPDATE
               SET alert_id=%(alert_id)s, alerter=%(alerter)s, operation=%(operation)s, 
                   received_time=%(received_time)s, start_time=%(start_time)s, end_time=%(end_time)s, 
                   success=%(success)s, skipped=%(skipped)s, retries=%(retries)s, response=%(response)s, 
                   reason=%(reason)s, bg_task_id=%(bg_task_id)s, task_chain_info=%(task_chain_info)s
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

    def get_last_executing_operation(self, alert_id: str, alerter: str) -> Optional[AlerterOperationData]:
        query = """
            SELECT *
              FROM alerter_data
             WHERE alert_id=%(alert_id)s
               AND alerter=%(alerter)s
               AND operation <> 'recovery'
               AND received_time IS NOT NULL
               AND end_time IS NULL
             ORDER BY received_time DESC
             LIMIT 1
        """
        record = self.backend._fetchone(query, dict(alert_id=alert_id, alerter=alerter))
        return AlerterOperationData.from_record(record) if record else None

    def clear_alerters_data(self, alert_id: str):
        delete = """
            DELETE FROM alerter_data
             WHERE alert_id=%(alert_id)s
        """
        self.backend._deleteall(delete, dict(alert_id=alert_id))

    # -----------------------
    # Recovery actions
    # -----------------------

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

    # ------------------------
    # Key/Value store
    # ------------------------
    def get_value_from_key(self, key):
        query = """
            SELECT * FROM key_value_store WHERE key=%(key)s
        """
        record = self.backend._fetchone(query, dict(key=key))
        return KeyValueParameter.from_record(record) if record else None

    def create_key_value(self, key_value: KeyValueParameter):
        insert = """
            INSERT INTO key_value_store (key, value)
            VALUES (%(key)s, %(value)s)
         RETURNING *
        """
        record = self.backend._insert(insert, vars(key_value))
        return KeyValueParameter.from_record(record) if record else None

    def update_key_value(self, key_value: KeyValueParameter):
        update = """
            UPDATE key_value_store
               SET value=%(value)s
             WHERE key=%(key)s 
         RETURNING *
        """
        record = self.backend._updateone(update, vars(key_value), returning=True)
        if record is None:
            record = self.create_key_value(key_value)
        return KeyValueParameter.from_record(record) if record else None

    # ------------------------
    # Alert contextual rules
    # ------------------------
    def get_contextual_rule(self, name: str):
        query = """
            SELECT *
              FROM alert_contextual_rules
              WHERE name=%(name)s
        """
        record = self.backend._fetchone(query, dict(name=name))
        return ContextualRule.from_record(record) if record else None

    def get_all_contextual_rules(self, limit: int, offset: int):
        query = """
            SELECT *
            FROM alert_contextual_rules
            ORDER BY priority DESC
        """
        records = self.backend._fetchall(query, vars={}, limit=limit, offset=offset)
        data = []
        for record in records:
            data.append(ContextualRule.from_record(record).__dict__)
        return data

    def update_contextual_rule(self, rule: ContextualRule):
        update = """
            UPDATE alert_contextual_rules
            SET name=%(name)s, rules=%(contextual_rules)s,
                context=%(context)s, priority=%(priority)s,
                last_check=%(last_check)s
            WHERE id=%(id)s 
            RETURNING *
        """
        record = self.backend._updateone(update, vars(rule), returning=True)
        return KeyValueParameter.from_record(record) if record else None

    def create_contextual_rule(self, rule: ContextualRule):
        insert = """
            INSERT INTO alert_contextual_rules (name, rules, context, priority, last_check)
            VALUES (%(name)s, %(contextual_rules)s, %(context)s, %(priority)s, %(last_check)s)
            RETURNING *
         """
        record = self.backend._insert(insert, vars(rule))
        return ContextualRule.from_record(record) if record else None

    def delete_contextual_rule(self, rule_id: int):
        delete = """
            DELETE FROM alert_contextual_rules
            WHERE id=%(id)s
            RETURNING *
        """
        resp = self.backend._deleteall(delete, dict(rule_id=rule_id), returning=True)
        return len(resp) != 0

    # ------------------------
    # Alert dependencies
    # ------------------------
    def get_alert_dependency(self, resource: str, event: str):
        query = """
            SELECT *
            FROM alert_dependency
            WHERE resource=%(resource)s AND event=%(event)s
        """
        record = self.backend._fetchone(query, dict(resource=resource, event=event))
        return AlertDependency.from_record(record) if record else None

    def get_all_alert_dependencies(self, limit: int, offset: int):
        query = """
            SELECT *
            FROM alert_dependency 
            ORDER BY resource, event
        """
        records = self.backend._fetchall(query, vars={}, limit=limit, offset=offset)
        data = []
        for record in records:
            data.append(AlertDependency.from_record(record).__dict__)
        return data

    def update_alert_dependency(self, alert_dependency: AlertDependency):
        update = """
            UPDATE alert_dependency
            SET dependencies = %(dependencies)s
            WHERE resource = %(resource)s and event = %(event)s
            RETURNING *
        """
        record = self.backend._updateone(update, vars(alert_dependency), returning=True)
        return KeyValueParameter.from_record(record) if record else None

    def create_alert_dependency(self, alert_dependency: AlertDependency):
        insert = """
            INSERT INTO alert_dependency (resource, event, dependencies)
            VALUES (%(resource)s, %(event)s, %(dependencies)s)
            RETURNING *
        """
        record = self.backend._insert(insert, vars(alert_dependency))
        return AlertDependency.from_record(record) if record else None

    def delete_alert_dependency(self, resource: str, event: str):
        delete = """
            DELETE FROM alert_dependency
            WHERE resource = %(resource)s AND event = %(event)s
            RETURNING *
        """
        resp = self.backend._deleteall(delete, dict(resource=resource, event=event), returning=True)
        return len(resp) != 0
