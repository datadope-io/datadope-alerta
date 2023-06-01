from typing import Optional
from alerta.database.backends.postgres.base import Backend


class AsyncAlert:
    instance: 'AsyncAlert' = None

    def __new__(cls, *args, **kwargs):
        instance = super().__new__(cls)
        cls.instance = instance
        return instance

    def __init__(self, db_backend: Backend):
        self.backend = db_backend

    def get_alert_id(self, bg_task_id) -> Optional[str | dict]:
        query = """
            SELECT alert_id, errors
              FROM async_alert
             WHERE bg_task_id=%(bg_task_id)s
        """
        record = self.backend._fetchone(query, dict(bg_task_id=bg_task_id))
        if record is None:
            raise KeyError(bg_task_id)
        return record.alert_id or record.errors

    def create(self, bg_task_id: str, alert_id: str = None) -> Optional[str]:
        insert = """
            INSERT INTO async_alert (alert_id, bg_task_id)
            VALUES (%(alert_id)s, %(bg_task_id)s)
            RETURNING *
        """
        record = self.backend._insert(insert, dict(bg_task_id=bg_task_id, alert_id=alert_id))
        return record.bg_task_id if record else None

    def update(self, bg_task_id: str, alert_id: str, errors: dict = None) -> Optional[str]:
        update = """
                    UPDATE async_alert 
                       SET alert_id=%(alert_id)s, errors=%(errors)s
                     WHERE bg_task_id=%(bg_task_id)s
                     RETURNING *
                """
        record = self.backend._updateone(update,
                                         dict(bg_task_id=bg_task_id, alert_id=alert_id, errors=errors),
                                         returning=True)
        return record.bg_task_id if record else None
