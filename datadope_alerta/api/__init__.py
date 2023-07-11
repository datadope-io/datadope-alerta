from flask import Blueprint

iom_api = Blueprint('iom_api', __name__)

from . import alerters, contextualizer, async_alert, alert_dependency # noqa isort:skip
