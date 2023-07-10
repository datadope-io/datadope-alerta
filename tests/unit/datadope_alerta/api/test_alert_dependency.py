import json

import pytest
from redis.commands.search import query

from datadope_alerta.api.alert_dependency import AlertDependenciesApi
from datadope_alerta.backend.flexiblededup.models.alert_dependency import AlertDependency
from datadope_alerta.backend.flexiblededup.specific import SpecificBackend
from alerta.database.backends.postgres.base import Backend


# noinspection SpellCheckingInspection
def _create_alert_dependency(resource: str, event: str, dependencies: str):
    return AlertDependency.from_dict({
        'resource': resource,
        'event': event,
        'dependencies': dependencies
    })


# noinspection PyProtectedMember,SpellCheckingInspection
class TestsContextualizer:

    @pytest.fixture()
    def set_up_api(self):
        return AlertDependenciesApi()

    @pytest.fixture()
    def set_up_backend(self):
        return SpecificBackend.instance

    @pytest.fixture()
    def get_request_with_body(self):
        dependencies = [
            {
                'resource': 'resource02',
                'event': 'event02'
            }
        ]
        with pytest.app.app_context():
            with pytest.app.test_request_context(json={
                'resource': 'resource012',
                'event': 'event012',
                'dependencies': json.dumps(dependencies)
            }
            ):
                yield

    @pytest.fixture()
    def get_request(self):
        with pytest.app.app_context():
            with pytest.app.test_request_context():
                yield

    def test_read_alert_dependency(self, get_request, set_up_api, set_up_backend):
        dependencies = [
            {
                'resource': 'resource002',
                'event': 'event002'
            }
        ]
        set_up_backend.create_alert_dependency(
            _create_alert_dependency(
                'resource001',
                'event001',
                json.dumps(dependencies)
            )
        )
        response = set_up_api.read_alert_dependency('resource001', 'event001')

        assert ('dependencies', 'event', 'resource') == tuple(response.json.keys())

    def test_read_alert_dependency_fails(self, get_request, set_up_api):
        response = set_up_api.read_alert_dependency('resource2', 'event2')
        assert isinstance(response.json, list)
        assert len(response.json) == 0

    def test_read_all_alert_dependencies(self, get_request, set_up_api):
        response = set_up_api.read_all_alert_dependencies()
        assert isinstance(response.json, list)

    def test_add_alert_dependency(self, get_request_with_body, set_up_api):
        response = set_up_api.create_alert_dependency()
        assert response.json['resource'] == 'resource012'
        assert response.json['event'] == 'event012'

    def test_add_alert_dependency_fails(self, get_request, set_up_api):
        with pytest.raises(Exception):
            set_up_api.create_rule()
