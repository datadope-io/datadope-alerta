from abc import ABC, abstractmethod

from alerta.models.alert import Alert
from datadope_alerta import VarDefinition

BLACKOUT_PROVIDERS =  VarDefinition('blackoutProviders', ['internal'])
BLACKOUT_TASK_INTERVAL =  VarDefinition('blackoutTaskInterval', 300)
BLACKOUT_TASK_QUEUE =  VarDefinition('blackoutTaskQueue', 'blackout')

class BlackoutProvider(ABC):

    @abstractmethod
    def is_alert_in_blackout(self, alert: Alert, config) -> bool:
        """
        Check if an alert is in a blackout period.

        :param alert: Alert to check if it is in blackout
        :param config: server configuration
        :return: True if alert is considered to be in blackout
        """
        pass