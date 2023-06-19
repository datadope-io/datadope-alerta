from typing import List
from alerta.database.backends.postgres.base import Backend


class ExternalReferencesBackend:
    instance: 'ExternalReferencesBackend' = None

    def __new__(cls, *args, **kwargs):
        instance = super().__new__(cls)
        cls.instance = instance
        return instance

    def __init__(self, db_backend: Backend):
        self.backend = db_backend

    def get_references(self, alert_id, platform) -> List[str]:
        query = """
            SELECT reference
              FROM external_references
             WHERE alert_id=%(alert_id)s
               AND platform=%(platform)s
        """
        records = self.backend._fetchall(query, dict(alert_id=alert_id, platform=platform))
        return [x.reference for x in records]

    def insert(self, alert_id: str, platform: str, reference: str) -> bool:
        """
        Inserts a new record if there is no record with the same that.

        :param alert_id:
        :param platform:
        :param reference:
        :return: True if a new record is inserted
        """
        insert = """
            INSERT INTO external_references (alert_id, platform, reference)
            VALUES (%(alert_id)s, %(platform)s, %(reference)s)
            ON CONFLICT ON CONSTRAINT external_references_pkey DO NOTHING
            RETURNING *
        """
        record = self.backend._insert(insert, dict(alert_id=alert_id, platform=platform,
                                                   reference=str(reference)))
        return True if record else False
