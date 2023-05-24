from flask import Blueprint

iom_api = Blueprint('iom_api', __name__)

from . import alerters, async_alert  # noqa isort:skip
