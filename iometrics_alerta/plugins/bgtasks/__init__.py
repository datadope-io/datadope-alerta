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

from iometrics_alerta import init_configuration, init_jinja_loader, init_alerters_backend
from iometrics_alerta.plugins import getLogger
# noinspection PyUnresolvedReferences
from iometrics_alerta.plugins import prepare_result, result_for_exception

app = create_app()
celery = create_celery_app(app)

logger = getLogger('bgtasks')

init_configuration(app.config)
init_jinja_loader(app)
init_alerters_backend()


def revoke_task(task_id):
    celery.control.revoke(task_id)


# Import all tasks to ensure celery finds them including only the package in CELERTY_IMPORTS
from .auto_close import check_automatic_closing  # noqa - To provide import for package modules

from .recovery_actions import launch_actions  # noqa - To provide import for package modules

# Tasks defined as classes must be instantiated and registered
from .alert import event_task, recovery_task, repeat_task # noqa - To provide import for package modules
