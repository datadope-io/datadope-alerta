import json

import requests

from datadope_alerta.plugins import getLogger

DEFAULT_VERIFY_SSL = True
DEFAULT_CONNECT_TIMEOUT = 15.1
DEFAULT_READ_TIMEOUT = 60.0

logger = getLogger(__name__)


class ConnectionFields:
    __slots__ = ()

    BASE_URL = ('base_url', 'url', 'endpoint')
    USERNAME = ('username', 'user')
    PASSWORD = ('api_token', 'password')
    BEARER_TOKEN = 'bearer_token'
    HEADERS = 'headers'
    VERIFY_SSL = ('verify_ssl', 'verify')
    CONNECT_TIMEOUT = ('connect_timeout', 'timeout')
    READ_TIMEOUT = ('read_timeout', 'timeout')
    PROXIES = 'proxies'

    @staticmethod
    def get_field_value(field_name, connection_data, default=None):
        if isinstance(field_name, str):
            return connection_data.get(field_name)
        for name in field_name:
            value = connection_data.get(name)
            if value:
                return value
        return default


class RequestFields:
    __slots__ = ()

    ENDPOINT = "endpoint"
    METHOD = "method"
    HEADERS = "headers"
    PARAMS = "params"
    DATA = "data"
    PAYLOAD = "payload"


class JiraClient:
    def __init__(self, **kwargs):
        kwargs = {k.lower(): v for k, v in kwargs.items()}
        self.base_url = ConnectionFields.get_field_value(ConnectionFields.BASE_URL, kwargs)
        if not self.base_url:
            raise ValueError('Jira URL is not specified')
        if self.base_url.endswith('/'):
            self.base_url = self.base_url[:-1]
        self.headers = ConnectionFields.get_field_value(ConnectionFields.HEADERS, kwargs)
        if isinstance(self.headers, str):
            self.headers = json.loads(self.headers)
        bearer_token = ConnectionFields.get_field_value(ConnectionFields.BEARER_TOKEN, kwargs)
        if bearer_token:
            self.headers['Authorization'] = f"Bearer {bearer_token}"
            self.auth = None
        else:
            user = ConnectionFields.get_field_value(ConnectionFields.USERNAME, kwargs)
            if not user:
                raise ValueError('Jira username is not specified')
            password = ConnectionFields.get_field_value(ConnectionFields.PASSWORD, kwargs)
            if not password:
                raise ValueError('Jira password or api_token is not specified')
            self.auth = (user, password)
        self.verify_ssl = str(ConnectionFields.get_field_value(
            ConnectionFields.VERIFY_SSL, kwargs, default=DEFAULT_VERIFY_SSL)).lower() not in ('false', 'no', '0')
        self.connect_timeout = float(ConnectionFields.get_field_value(
            ConnectionFields.CONNECT_TIMEOUT, kwargs, default=DEFAULT_CONNECT_TIMEOUT))
        self.read_timeout = float(ConnectionFields.get_field_value(
            ConnectionFields.READ_TIMEOUT, kwargs, default=DEFAULT_READ_TIMEOUT))
        self.proxies = ConnectionFields.get_field_value(ConnectionFields.PROXIES, kwargs, default={})
        if isinstance(self.proxies, str):
            self.proxies = json.loads(self.proxies)

    def request(self, endpoint, method='POST', payload: dict = None, payload_extra_fields: dict = None,
                data=None, headers=None, params=None):
        if endpoint.startswith('http'):
            url = endpoint
        else:
            if not endpoint.startswith('/'):
                endpoint = f"/{endpoint}"
            url = f"{self.base_url}{endpoint}"
        headers = {**self.headers, **headers} if headers else self.headers
        if not isinstance(payload, dict):
            data = payload
            payload = None
        elif payload_extra_fields:
            payload = {**payload, **payload_extra_fields}
        logger.debug('Requesting %s %s', method, url)
        return requests.request(url=url, method=method, headers=headers, params=params, json=payload, data=data,
                                auth=self.auth, proxies=self.proxies,  verify=self.verify_ssl,
                                timeout=(self.connect_timeout, self.read_timeout))
