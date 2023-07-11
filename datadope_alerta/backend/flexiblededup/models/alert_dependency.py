from typing import Optional, List, Dict


class AlertDependency:
    __db = None

    def __init__(self, **kwargs):
        self.resource: str = kwargs.get('resource', None)
        self.event: str = kwargs.get('event', None)
        self.dependencies: Optional[List[Dict]] = kwargs.get('dependencies')

    @classmethod
    def get_db(cls):
        if cls.__db is None:
            from ..specific import SpecificBackend
            cls.__db = SpecificBackend.instance
        return cls.__db

    @classmethod
    def one_from_db(cls, resource, event) -> Optional['AlertDependency']:
        return cls.get_db().get_alert_dependency(resource, event)

    @classmethod
    def all_from_db(cls, limit: int, offset: int) -> list['AlertDependency']:
        return cls.get_db().get_all_alert_dependencies(limit, offset)

    @classmethod
    def add_to_db(cls, alert_dependency: 'AlertDependency'):
        return cls.get_db().create_alert_dependency(alert_dependency=alert_dependency)

    @classmethod
    def update_from_db(cls, alert_dependency: 'AlertDependency'):
        return cls.get_db().update_alert_dependency(alert_dependency=alert_dependency)

    @classmethod
    def from_record(cls, rec) -> 'AlertDependency':
        return AlertDependency(
            resource=rec.resource,
            event=rec.event,
            dependencies=rec.dependencies
        )

    @classmethod
    def from_dict(cls, json):
        if isinstance(json, str):
            import json as json_module
            json = json_module.loads(json)

        return AlertDependency(
            resource=json.get('resource', None),
            event=json.get('event', None),
            dependencies=json.get('dependencies')
        )

    @classmethod
    def clear(cls, resource, event):
        return cls.get_db().delete_alert_dependency(resource, event)
