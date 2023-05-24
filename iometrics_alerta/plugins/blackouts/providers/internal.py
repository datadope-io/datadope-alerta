from datetime import datetime

from alerta.models.alert import Alert
from iometrics_alerta.plugins.blackouts import BLACKOUT_PROVIDERS, BlackoutProvider

class Provider(BlackoutProvider):

    def is_alert_in_blackout(self, alert: Alert) -> bool:
        return alert.is_blackout()

