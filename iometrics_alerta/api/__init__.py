from flask import Blueprint

iom_api = Blueprint('iom_api', __name__)

from . import alerters  # noqa isort:skip
