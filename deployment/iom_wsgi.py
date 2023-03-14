from alerta import create_app
from iometrics_alerta import is_initialized, initialize

app = create_app()

# IOMetrics Alerta initialization
if not is_initialized():
    initialize(app)
