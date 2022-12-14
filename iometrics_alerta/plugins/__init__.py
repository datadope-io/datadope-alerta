import traceback
from abc import ABC, abstractmethod
from enum import Enum
from importlib import import_module
from typing import Any, Dict, Tuple, Optional, Union

# noinspection PyPackageRequirements
from celery.utils.log import get_task_logger

from alerta.models.alert import Alert
from iometrics_alerta import ContextualConfiguration, ConfigurationContext, VarDefinition, \
    ConfigKeyDict, render_template


def getLogger(name):  # noqa
    return get_task_logger(name)


logger = getLogger('iometrics_alerta.plugins')


class RetryableException(Exception):
    """
    IOMetrics asynchronous alerters plugins may raise this exception to ensure a retry of the task is scheduled
    (if retries are enabled and the limit of retries ha not been reached).

    Apart from this kind of exceptions, exceptions derived from the following exception types make tasks to be
    retried:
        - ConnectionError
        - requests.exceptions.ConnectionError
        - requests.exceptions.Timeout
    """
    pass


class AlerterStatus(str, Enum):
    New = 'new'
    Scheduled = 'scheduled'
    Processing = 'processing'
    Processed = 'processed'
    Recovering = 'recovering'
    Recovered = 'recovered'

    @classmethod
    def _missing_(cls, value):
        return cls.New


class Alerter(ABC):
    def __init__(self, name, config):
        self.name = name
        self.config = ConfigKeyDict(config)

    @staticmethod
    def get_fullname(klass):
        module = klass.__module__
        if module == 'builtins':
            return klass.__qualname__  # avoid outputs like 'builtins.str'
        return '.'.join((module, klass.__qualname__))

    @staticmethod
    def get_alerter_type(alerter_class):
        module_str, class_ = alerter_class.rsplit('.', 1)
        module = import_module(module_str)
        return getattr(module, class_)

    @staticmethod
    def failure_response(reason, message, extra_info: Optional[Union[Exception, Dict[str, Any], str]] = None):
        data = {
            'reason': reason,
            'info': {
                'message': message
            }
        }
        if isinstance(extra_info, Exception):
            data['info'].update({
                'type': type(extra_info).__name__,
                'traceback': ''.join(traceback.format_exception(type(extra_info), extra_info, extra_info.__traceback__))
            })
        elif isinstance(extra_info, dict):
            data['info'].update(extra_info)
        elif extra_info:
            data['info']['extra_info'] = str(extra_info)
        return data

    def get_contextual_configuration(self, var_definition: VarDefinition,
                                     alert: Alert, operation: str) -> Tuple[Any, ConfigurationContext]:
        """
        Helper method to get a configuration value from the alert or from alerter configuration

        :param var_definition:
        :param alert:
        :param operation:
        :return:
        """
        return ContextualConfiguration.get_contextual_alerter_config(var_definition, alert=alert,
                                                                     alerter=self, operation=operation)

    @staticmethod
    def get_event_tags(alert, operation=None):
        """
        Helper method for alerters to get full eventTags dictionary (keys normalized)
        """
        return ContextualConfiguration.get_event_tags(alert, operation)

    def render_template(self, template_path, alert, operation=None):
        """
        Helper method for alerters to render a file formatted as Jinja2 template.

        Template may use the variables:
          * alert: alert object
          * attributes: alert attributes dict (keys normalized)
          * event_tags: alert eventTags attribute  dict (keys normalized)
          * config: alerter configuration dict (keys normalized)
        :param template_path:
        :param alert:
        :param operation:
        :return:
        """
        attributes = ConfigKeyDict(alert.attributes)
        event_tags = self.get_event_tags(alert, operation)
        return render_template(template_path,
                               alert=alert,
                               attributes=attributes,
                               event_tags=event_tags,
                               config=self.config)

    @abstractmethod
    def process_event(self, alert: 'Alert', reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        pass

    @abstractmethod
    def process_recovery(self, alert: 'Alert', reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        pass
