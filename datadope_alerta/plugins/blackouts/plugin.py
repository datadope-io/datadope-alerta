import logging
from typing import List, Tuple, Callable

from pkg_resources import iter_entry_points

from alerta.exceptions import BlackoutPeriod
from alerta.plugins import PluginBase

from datadope_alerta import ContextualConfiguration

from . import BLACKOUT_PROVIDERS, BLACKOUT_TASK_INTERVAL, BlackoutProvider

logger = logging.getLogger(__name__)

class BlackoutManager(PluginBase):
    _entry_points: dict = None

    def __init__(self, name=None):
        super().__init__(name)
        self._get_installed_providers()

    @classmethod
    def _get_installed_providers(cls):
        if cls._entry_points is None:
            func_name = BlackoutProvider.is_alert_in_blackout.__name__
            cls._entry_points = {}
            for ep in iter_entry_points('alerta.blackout.providers'):
                try:
                    provider = ep.load()
                    if provider:
                        obj = provider()
                        func = getattr(obj, func_name)
                        if not callable(func):
                            raise Exception(f"Function '{func_name}' is not callable")
                        cls._entry_points[ep.name] = provider()
                        logger.info("Blackout provider '%s' loaded.", ep.name)
                except Exception as e:
                    logger.error("Failed to load blackout provider '%s': %s", ep.name, str(e))
        return cls._entry_points

    @classmethod
    def get_providers(cls, alert, config) -> dict[str, BlackoutProvider]:
        provider_names =  ContextualConfiguration.get_global_attribute_value(BLACKOUT_PROVIDERS, alert,
                                                                    None, config)
        providers = {}
        for name in provider_names:
            provider = cls._entry_points.get(name)
            if not provider:
                logger.warning("Provider '%s' not installed", name)
            else:
                providers[name] = provider
        return providers

    @classmethod
    def is_alert_in_blackout(cls, alert, config):
        # If alert has to be rejected but severity in BLACKOUT_ACCEPT, create alert ignoring blckout
        if not config['NOTIFICATION_BLACKOUT'] and alert.severity in config['BLACKOUT_ACCEPT']:
            return False

        providers = cls.get_providers(alert, config)
        for name, provider in providers.items():
            try:
                if provider.is_alert_in_blackout(alert):
                    logger.info("Alert marked in blackout by provider '%s'", name)
                    return True
            except Exception as e:
                logger.warning("Unhandled exception raised by blackout provider '%s': %s", name, str(e))
        return False

    def pre_receive(self, alert, **kwargs):
        config = kwargs.get("config")
        notification_blackout = self.get_config('NOTIFICATION_BLACKOUT', default=True, type=bool, **kwargs)

        if self.get_config('ALARM_MODEL', **kwargs) == 'ALERTA':
            status = 'blackout'
        else:
            status = 'OOSRV'  # ISA_18_2

        if self.is_alert_in_blackout(alert, config):
            if notification_blackout:
                logger.debug(f'Set status to "{status}" during blackout period (id={alert.id})')
                alert.status = status
            else:
                logger.debug(f'Suppressed alert during blackout period (id={alert.id})')
                raise BlackoutPeriod('Suppressed alert during blackout period')
        return alert

    def post_receive(self, alert, **kwargs):
        return

    def status_change(self, alert, status, text, **kwargs):
        return

    def take_action(self, alert, action, text, **kwargs):
        raise NotImplementedError

    def delete(self, alert, **kwargs) -> bool:
        raise NotImplementedError

    def register_periodic_tasks(self, config) -> List[Tuple[Callable, float]]:  # noqa
        from datadope_alerta.bgtasks.blackouts import check_still_in_blackout
        interval = float(ContextualConfiguration.get_global_configuration(BLACKOUT_TASK_INTERVAL, config))
        return [
            (check_still_in_blackout, interval)
        ]