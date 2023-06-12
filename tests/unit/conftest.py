import pytest

from alerta import create_app

from datadope_alerta import is_initialized, initialize


def pytest_configure():
    config = {
        'TESTING': True,
        'AUTH_REQUIRED': False
    }
    app = create_app(config)
    if not is_initialized():
        initialize(app)
    pytest.app = app
