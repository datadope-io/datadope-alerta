from alerta import create_app
from datadope_alerta import is_initialized, initialize

app = create_app()

from datadope_alerta.api import iom_api  # noqa isort:skip
app.register_blueprint(iom_api)


# IOMetrics Alerta initialization
if not is_initialized():
    initialize(app)
