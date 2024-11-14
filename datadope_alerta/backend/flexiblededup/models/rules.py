from typing import Optional


class ContextualRule:
    __db = None

    def __init__(self, name, **kwargs):
        self.name: str = name
        self.id: Optional[int] = kwargs.get('id', None)
        self.contextual_rules: list = kwargs.get('contextual_rules')
        self.context: dict = kwargs.get('context')
        self.priority: int = kwargs.get('priority', 1000)
        self.last_check: bool = kwargs.get('last_check', False)
        self.append_lists: bool = kwargs.get('append_lists', True)

    @classmethod
    def get_db(cls):
        if cls.__db is None:
            from ..specific import SpecificBackend
            cls.__db = SpecificBackend.instance
        return cls.__db

    @classmethod
    def one_from_db(cls, name) -> Optional['ContextualRule']:
        contextual_rule = cls.get_db().get_contextual_rule(name)
        return contextual_rule

    @classmethod
    def all_from_db(cls, limit: int, offset: int) -> list['ContextualRule']:
        contextual_rules = cls.get_db().get_all_contextual_rules(limit, offset)
        return contextual_rules

    @classmethod
    def from_record(cls, rec) -> 'ContextualRule':
        return ContextualRule(
            id=rec.id,
            name=rec.name,
            contextual_rules=rec.rules,
            context=rec.context,
            priority=rec.priority,
            last_check=rec.last_check,
            append_lists=rec.append_lists
        )

    @classmethod
    def from_dict(cls, json: dict):
        return ContextualRule(
            id=json.get('id', None),
            name=json.get('name'),
            contextual_rules=json.get('contextual_rules'),
            context=json.get('context'),
            priority=json.get('priority'),
            last_check=json.get('last_check'),
            append_lists=json.get('append_lists', True)
        )

    def store(self):
        if self.id is None:
            return self.get_db().create_contextual_rule(self)
        else:
            return self.get_db().update_contextual_rule(self)

    @classmethod
    def clear(cls, rule_id):
        return cls.get_db().delete_contextual_rule(rule_id)
