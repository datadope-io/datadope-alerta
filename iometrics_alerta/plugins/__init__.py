import traceback
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from importlib import import_module
from typing import Any, Dict, Tuple, Optional, Union

# noinspection PyPackageRequirements
from celery.utils.log import get_task_logger

from alerta.models.alert import Alert
from iometrics_alerta import ContextualConfiguration, ConfigurationContext, VarDefinition, \
    ConfigKeyDict, render_template, AlerterProcessAttributeConstant, DateTime


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
    Repeating = 'repeating'
    Processed = 'processed'
    Recovering = 'recovering'
    Recovered = 'recovered'

    @classmethod
    def _missing_(cls, value):
        return cls.New


class Alerter(ABC):

    def __init__(self, name, config, bgtask=None):
        self.name = name
        self.config = ConfigKeyDict(config)
        self.bgtask = bgtask

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

    @abstractmethod
    def process_repeat(self, alert: 'Alert', reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        pass


ATTRIBUTE_KEYS_BY_OPERATION = {
    Alerter.process_event.__name__: AlerterProcessAttributeConstant.KEY_NEW_EVENT,
    Alerter.process_recovery.__name__: AlerterProcessAttributeConstant.KEY_RECOVERY,
    Alerter.process_repeat.__name__: AlerterProcessAttributeConstant.KEY_REPEAT
}


def prepare_result(status: AlerterStatus, data_field: str,
                   retval: Union[Dict[str, Any], Tuple[bool, Dict[str, Any]]],
                   start_time: datetime = None, end_time: datetime = None,
                   duration: float = None, skipped: bool = None, retries: int = None) -> Tuple[bool, Dict[str, Any]]:
    if isinstance(retval, tuple):
        result = {
            AlerterProcessAttributeConstant.FIELD_SUCCESS: retval[0],
            AlerterProcessAttributeConstant.FIELD_RESPONSE: retval[1]
        }
    else:
        result = {
            AlerterProcessAttributeConstant.FIELD_SUCCESS: True,
            AlerterProcessAttributeConstant.FIELD_RESPONSE: retval
        }
    if start_time:
        result[AlerterProcessAttributeConstant.FIELD_START] = DateTime.iso8601_utc(start_time)
    if end_time:
        result[AlerterProcessAttributeConstant.FIELD_END] = DateTime.iso8601_utc(end_time)
    if duration is None and start_time is not None and end_time is not None:
        duration = (end_time - start_time).total_seconds()
    if duration is not None:
        result[AlerterProcessAttributeConstant.FIELD_ELAPSED] = duration
    if skipped is not None:
        result[AlerterProcessAttributeConstant.FIELD_SKIPPED] = skipped
    if retries:
        result[AlerterProcessAttributeConstant.FIELD_RETRIES] = retries
    return result[AlerterProcessAttributeConstant.FIELD_SUCCESS], {
            AlerterProcessAttributeConstant.FIELD_STATUS: status.value,
            data_field: result
    }


def result_for_exception(exc, einfo=None, include_traceback=False):
    if exc is None and einfo is None:
        try:
            raise Exception('Failure without exception')
        except Exception as e:
            exc = e
    result = {
        'reason': 'exception',
        'info': {
            'message': str(exc or einfo.exception),
            'type': (type(exc) if exc else einfo.type).__name__
        }
    }
    if include_traceback:
        result['info']['traceback'] = ''.join(traceback.format_exception(
            type(exc), exc, exc.__traceback__)) if exc else einfo.traceback
    return result


def has_alerting_succeeded(alert, alerter_attribute_name):
    success = alert.attributes.get(alerter_attribute_name, {}) \
        .get(AlerterProcessAttributeConstant.KEY_NEW_EVENT, {})\
        .get(AlerterProcessAttributeConstant.FIELD_SUCCESS, False)
    return success
