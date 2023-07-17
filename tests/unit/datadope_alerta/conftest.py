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
