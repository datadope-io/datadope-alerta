import pytest

from alerta import create_app


def pytest_configure():
    config = {
        'TESTING': True,
        'AUTH_REQUIRED': False
    }
    app = create_app(config)
    pytest.app = app
