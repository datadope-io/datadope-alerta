class ExternalReferences:
    __db = None

    @classmethod
    def get_db(cls):
        if cls.__db is None:
            from ..external_references import ExternalReferencesBackend
            cls.__db = ExternalReferencesBackend.instance
        return cls.__db

    @classmethod
    def insert(cls, alert_id, platform, reference):
        return cls.get_db().insert(alert_id, platform, str(reference))

    @classmethod
    def get_references(cls, alert_id, platform):
        return cls.get_db().get_references(alert_id, platform)
