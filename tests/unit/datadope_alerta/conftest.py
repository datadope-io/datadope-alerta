import pytest


@pytest.fixture(autouse=True)
def get_app():
    with pytest.app.app_context():
        yield


@pytest.fixture()
def get_request():
    with pytest.app.app_context():
        with pytest.app.test_request_context():
            yield


@pytest.fixture()
def get_request_with_body():
    with pytest.app.app_context():
        with pytest.app.test_request_context(json={
            'name': 'rule2',
            'contextual_rules': {'event': 'NodeDown'},
            'context': {'event': 'A data node is down'},
            'priority': 2000,
            'last_check': True
        }):
            yield
