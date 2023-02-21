import json
import traceback
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from importlib import import_module
from json import JSONDecodeError
from typing import Any, Dict, Tuple, Optional, Union

# noinspection PyPackageRequirements
from celery.utils.log import get_task_logger
# noinspection PyPackageRequirements
from jinja2 import TemplateNotFound

from alerta.models.alert import Alert
from iometrics_alerta import ContextualConfiguration, ConfigurationContext, VarDefinition, \
    ConfigKeyDict, render_template, AlerterProcessAttributeConstant, DateTime, \
    alert_pretty_json_string, safe_convert, render_value, ALERTER_SPECIFIC_CONFIG_KEY_SUFFIX, get_config, merge, \
    AlertIdFilter


def getLogger(name):  # noqa
    filter_ = AlertIdFilter.get_instance()
    logger_ = get_task_logger(name)
    logger_.addFilter(filter_)
    return logger_


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

    _alerter_config = None

    def __init__(self, name, bgtask=None):
        self.name = name
        self.bgtask = bgtask
        self.config = ConfigKeyDict(self.get_alerter_config(self.name))

    @classmethod
    @abstractmethod
    def get_default_configuration(cls) -> dict:
        """
        Provides alerter default configuration overridable with an environment value.

        :return:
        """
        pass

    @classmethod
    def get_alerter_config(cls, alerter_name) -> Dict[str, Any]:
        """
        Reads alerter config using global app configuration. First get default configuration
        from alerter and merges it with configuration from environment or config file.

        Configuration key retrieved will be form as'<ALERTER_NAME>_CONFIG'
        (using uppercase form of alerter_name property).

        Override to implement a different mechanism to get the config for the alerter.

        :return: alerter configuration
        """
        if cls._alerter_config is None:
            default = cls.get_default_configuration() or {}
            config_key = f"{alerter_name.upper()}{ALERTER_SPECIFIC_CONFIG_KEY_SUFFIX}"
            config = get_config(config_key, default={})
            if isinstance(config, str):
                try:
                    config = json.loads(config)
                except JSONDecodeError:
                    logger.error("Wrong configuration for alerter '%s': '%s'",
                                 alerter_name, config)
                    config = {}
            cls._alerter_config = merge(default, config)
        return cls._alerter_config

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

    def get_alerter_data_for_alert(self, alert, operation: str) -> dict:
        """
        Helper method to return alerter specific data received as an alert attribute.

        Alerter specif data atttrinute name is formed as <alerter_name><ALERTER_SPECIFIC_CONFIG_KEY_SUFFIX>,
        and is searched in alert attributes using normalized keys.
        ALERTER_SPECIFIC_CONFIG_KEY_SUFFIX is '_CONFIG' by default.
        So for an alerter with name "email" the expected attribute name would be email_CONFIG.
        Every normalized format of "email_CONFIG" would match the attribute.
        The preferred format would be camelCase: "emailConfig".

        Specific configuration for the operation may be provided so attributes: newEmailConfig, recoveryEmailConfig...
        are also valid and the correct one for the provided operation will be returned
        with priority against emailConfig.

        Moreover, different values for different operations may be configured inside the principal emailConfig
        attribute:
        emailConfig = {"new": {...}, "recovery": {...}, "repeat": {...}}

        :param alert:
        :param operation:
        :return:
        """
        data_key = self.name + ALERTER_SPECIFIC_CONFIG_KEY_SUFFIX
        alert_attributes = ConfigKeyDict(alert.attributes)
        alerter_data = alert_attributes.get_for_operation(data_key, operation, {})
        return safe_convert(alerter_data, dict, operation, default={})

    @staticmethod
    def get_event_tags(alert, operation=None):
        """
        Helper method for alerters to get full eventTags dictionary (keys normalized)
        """
        return ContextualConfiguration.get_event_tags(alert, operation)

    @staticmethod
    def get_event_tag(tag, alert, type_=None, operation=None, default=None):
        tags = Alerter.get_event_tags(alert, operation)
        return safe_convert(tags.get(tag, default), type_=type_, operation=operation)

    def render_template(self, template_path, alert, operation=None):
        """
        Helper method for alerters to render a file formatted as Jinja2 template.

        Template may use the variables:
          * alert: alert object
          * attributes: alert attributes dict (keys normalized)
          * event_tags: alert eventTags attribute  dict (keys normalized)
          * alerter_config: alerter configuration dict (keys normalized)
          * alerter_name: alerter name
          * operation: operation
          * operation_key: attribute key for operation. See 'ATTRIBUTE_KEYS_BY_OPERATION'
          * pretty_alert: alert serialization as pretty json
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
                               alerter_config=self.config,
                               alerter_name=self.name,
                               operation=operation,
                               operation_key=ATTRIBUTE_KEYS_BY_OPERATION[operation] if operation else None,
                               pretty_alert=alert_pretty_json_string(alert))

    def render_value(self, value, alert, operation=None):
        """
        Helper method for alerters to render a file formatted as Jinja2 template.

        Template may use the variables:
          * alert: alert object
          * attributes: alert attributes dict (keys normalized)
          * event_tags: alert eventTags attribute  dict (keys normalized)
          * alerter_config: alerter configuration dict (keys normalized)
          * alerter_name: alerter name
          * operation: operation
          * operation_key: attribute key for operation. See 'ATTRIBUTE_KEYS_BY_OPERATION'
          * pretty_alert: alert serialization as pretty json
        :param value:
        :param alert:
        :param operation:
        :return:
        """
        attributes = ConfigKeyDict(alert.attributes)
        event_tags = self.get_event_tags(alert, operation)
        return render_value(value,
                            alert=alert,
                            attributes=attributes,
                            event_tags=event_tags,
                            alerter_config=self.config,
                            alerter_name=self.name,
                            operation=operation,
                            operation_key=ATTRIBUTE_KEYS_BY_OPERATION[operation] if operation else None,
                            pretty_alert=alert_pretty_json_string(alert))

    @abstractmethod
    def process_event(self, alert: 'Alert', reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        pass

    @abstractmethod
    def process_recovery(self, alert: 'Alert', reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        pass

    @abstractmethod
    def process_repeat(self, alert: 'Alert', reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        pass

    def get_message(self, alert: Alert, operation: str) -> str:
        message = None
        template, _ = self.get_contextual_configuration(ContextualConfiguration.TEMPLATE_PATH, alert, operation)
        if template:
            try:
                message = self.render_template(template, alert=alert, operation=operation)
            except TemplateNotFound:
                logger.info("Template %s not found for email Alerter. Using other options to create message",
                            template)
            except Exception as e:
                logger.warning("Error rendering template: %s. Using other options to create message", e, exc_info=e)
        if message is None:
            message, _ = self.get_contextual_configuration(ContextualConfiguration.MESSAGE, alert, operation)
        return message

    def is_dry_run(self, alert: Alert, operation: str) -> bool:
        dry_run, _ = self.get_contextual_configuration(ContextualConfiguration.DRY_RUN, alert, operation)
        return dry_run


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
