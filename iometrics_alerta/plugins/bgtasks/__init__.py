from alerta.app import create_app, create_celery_app
# noinspection PyUnresolvedReferences
from alerta.app import db  # To provide import for package modules
# noinspection PyUnresolvedReferences
from alerta.models.alert import Alert  # To provide import for package modules
# noinspection PyUnresolvedReferences
from alerta.models.enums import Status  # To provide import for package modules
# noinspection PyUnresolvedReferences
from alerta.utils.collections import merge  # To provide import for package modules

# noinspection PyUnresolvedReferences
from alertaclient.api import Client as AlertaClient  # To provide import for package modules

from iometrics_alerta import initialize, is_initialized
from iometrics_alerta.plugins import getLogger


if not is_initialized():
    app = create_app()
    celery = create_celery_app(app)
    initialize(app)
else:
    from flask import current_app
    app = current_app
    celery = create_celery_app(app)

logger = getLogger('bgtasks')


def revoke_task(task_id):
    celery.control.revoke(task_id)


# Import all tasks to ensure celery finds them including only the package in CELERY_IMPORTS
from .periodic_tasks import check_automatic_closing # noqa - To provide import for package modules

from .recovery_actions import launch_actions  # noqa - To provide import for package modules

# Tasks defined as classes must be instantiated and registered
from .alert import event_task, recovery_task, repeat_task, action_task  # noqa - To provide import for package modules
