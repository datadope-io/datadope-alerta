from alerta.models.alert import Alert
from datadope_alerta.plugins.blackouts import BlackoutProvider

class Provider(BlackoutProvider):

    def is_alert_in_blackout(self, alert: Alert) -> bool:
        return alert.is_blackout()

