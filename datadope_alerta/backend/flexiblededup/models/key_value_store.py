from typing import Optional


class KeyValueParameter:
    __db = None

    @classmethod
    def get_db(cls):
        if cls.__db is None:
            from ..specific import SpecificBackend
            cls.__db = SpecificBackend.instance
        return cls.__db

    def __init__(self, key, value):
        self.key: str = key
        self.value: str = str(value)

    @classmethod
    def from_db(cls, key) -> Optional['KeyValueParameter']:
        return cls.get_db().get_value_from_key(key)

    @classmethod
    def from_record(cls, rec) -> 'KeyValueParameter':
        return KeyValueParameter(
            key=rec.key,
            value=rec.value
        )

    def store(self):
        return self.get_db().update_key_value(self)
