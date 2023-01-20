import json
import logging
import os
from collections.abc import MutableMapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Tuple, Optional

from dateutil import parser
# noinspection PyPackageRequirements
import flask
# noinspection PyPackageRequirements
import jinja2
import pytz

from alerta.utils.format import CustomJSONEncoder as AlertaCustomJSONEncoder


logger = logging.getLogger('iometrics_alerta')

CONFIG_PLUGINS = 'PLUGINS'
"""
Configuration var with the list of alerta plugins to use.
"""

CONFIG_AUTO_CLOSE_TASK_INTERVAL = 'AUTO_CLOSE_TASK_INTERVAL'
"""
Configuration var for the interval of the periodic task to manage auto close of alerts.

Default: 60 sec.
"""

DEFAULT_AUTO_CLOSE_TASK_INTERVAL = 60.0

ALERTER_DEFAULT_CONFIG_VALUE_PREFIX = 'ALERTERS_DEFAULT_'
"""
Default value for an alerter of a configuration parameter will be formed 
as '{ALERTER_DEFAULT_CONFIG_VALUE_PREFIX}<CONFIG_KEY>'
"""

ALERTER_SPECIFIC_CONFIG_KEY_SUFFIX = '_CONFIG'
"""
Alerter configuration will be formed as '<ALERTER_NAME>{ALERTER_SPECIFIC_CONFIG_KEY_SUFFIX}'.
"""


ALERTER_IGNORE = 'ignore'
"""
Name of the alerter to configure in alerters attribute to indicate that the alert must be ignored and
no alerter should be notified. It is the same of an empty array in that attribute.
"""

ALERTERS_TASK_BY_OPERATION = {
    'process_event': 'new',
    'process_recovery': 'recovery',
    'process_repeat': 'repeat'
}
"""
Defines the task name for each operation. This name will be used as 
field name of the alerter processing attribute, as the prefix of the event tags
for values specific by operation...

May be overriden by configuration.
"""

ALERTERS_TEMPLATES_LOCATION = os.path.abspath(os.path.join(os.path.dirname(__file__), '../templates'))
"""
Defines the location of templates for alerters. 

May be overriden by configuration.
"""


def get_task_name(operation):
    if operation not in ALERTERS_TASK_BY_OPERATION:
        logger.warning("Operation '%s' not configured. Using 'new'", operation)
        return 'new'
    return ALERTERS_TASK_BY_OPERATION[operation]


def render_value(value, **kwargs):
    if isinstance(value, dict):
        result = {}
        for k, v in value.items():
            result[k] = render_value(v, **kwargs)
        return result
    elif isinstance(value, list):
        result = []
        for el in value:
            result.append(render_value(el, **kwargs))
        return result
    elif isinstance(value, str):
        return flask.render_template_string(value, **kwargs)
    else:
        return value


def render_template(template_path, **kwargs):
    return flask.render_template(template_path, **kwargs)


class CustomJSONEncoder(AlertaCustomJSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, ConfigKeyDict):
            return o.store
        return super().default(o)


class AlerterProcessAttributeConstant:
    """
    Constants to manage alerter processing data that will be stored as an alert attribute.
    """
    __slots__ = ()

    ATTRIBUTE_FORMATTER = '{alerter_name}Data'
    """
    Name of the alert attribute that will store the information about the alert processing by an alerter.
    It is a format string based on the variable 'alerter_name' that will provide the name of the alerter.
    """

    KEY_NEW_EVENT = ALERTERS_TASK_BY_OPERATION['process_event']
    """
    Key name in the alerter attribute where processing info of the event is stored.
    """

    KEY_RECOVERY = ALERTERS_TASK_BY_OPERATION['process_recovery']
    """
    Key name in the alerter attribute where processing info of the recovery is stored.
    """

    KEY_REPEAT = ALERTERS_TASK_BY_OPERATION['process_repeat']
    """
    Key name in the alerter attribute where processing info of the repeat is stored.
    """

    # Field names of the info to store about the event/recovery processing.
    FIELD_STATUS = 'status'
    FIELD_RECEIVED = 'received'
    FIELD_START = 'start'
    FIELD_END = 'end'
    FIELD_ELAPSED = 'elapsed_time'
    FIELD_SUCCESS = 'success'
    FIELD_RESPONSE = 'response'
    FIELD_BG_TASK_ID = 'bgtask_id'
    FIELD_SKIPPED = 'skipped'
    FIELD_RETRIES = 'retries'
    FIELD_REPETITIONS = 'repetitions'
    FIELD_TEMP_RECOVERY_DATA = '_tmp_recovery_data'
    FIELD_TEMP_RECOVERY_DATA_TEXT = 'text'
    FIELD_TEMP_RECOVERY_DATA_TASK_DEF = 'task_def'


class BGTaskAlerterDataConstants:
    """
    Fields of the task information to be transferred to the celery worker
    """
    __slots__ = ()
    NAME = 'name'
    CLASS = 'class'
    CONFIG = 'config'
    PLUGIN = 'plugin_name'


class CustomFormatter(logging.Formatter):
    DEFAULT_FORMATTERS = {
        'alerta': '%(asctime)s %(name)s[%(process)d]: [%(levelname)s] %(message)s [in %(pathname)s:%(lineno)d]',
        'flask': '%(asctime)s %(name)s[%(process)d]: [%(levelname)s] %(message)s',
        'urllib3': '%(asctime)s %(name)s[%(process)d]: [%(levelname)s] %(message)s',
        'werkzeug': '%(asctime)s %(name)s[%(process)d]: %(message)s',
        'default': logging.BASIC_FORMAT
    }

    def __init__(self, formats, request_suffix):
        self.formatters = {**self.DEFAULT_FORMATTERS}
        if formats:
            self.formatters.update(formats)
        self.default_formatter = formats['default']
        self.request_suffix = request_suffix or '[[%(method)s request_id=%(request_id)s ip=%(remote_addr)s]]'
        super().__init__()

    def format(self, record):

        fmt = record.name.split('.').pop(0)
        format_str = self.formatters.get(fmt, self.default_formatter)
        if flask.has_request_context():
            format_str = f"{format_str} {self.request_suffix}"
        formatter = logging.Formatter(format_str)
        return formatter.format(record)


class DateTime:

    @staticmethod
    def make_aware_utc(dt: datetime, tz=None):
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            if tz is not None:
                dt = tz.localize(dt)
            else:
                dt = dt.astimezone(pytz.utc)
        return dt

    @staticmethod
    def iso8601_utc(dt: datetime) -> str:
        return dt.astimezone(pytz.utc).replace(microsecond=0).strftime('%Y-%m-%dT%H:%M:%S') \
            + f'.{int(dt.microsecond // 1000):03}Z'

    @staticmethod
    def parse_utc(date_str: str) -> Optional[datetime]:
        if not isinstance(date_str, str):
            return None
        try:
            return DateTime.make_aware_utc(datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%S.%fZ'), pytz.utc)
        except Exception:
            raise ValueError('dates must be ISO 8601 date format YYYY-MM-DDThh:mm:ss.sssZ')

    @staticmethod
    def parse(date_str: str) -> Optional[datetime]:
        if not isinstance(date_str, str):
            return None
        return parser.isoparse(date_str)

    @staticmethod
    def diff_seconds_utc(dt1, dt2):
        return (DateTime.make_aware_utc(dt1) - DateTime.make_aware_utc(dt2)).total_seconds()


def merge(dict1, dict2):
    """
    Merge two dictionaries.
    dict1 will have the final dictionary, but it is also returned to allow to make a chain of merge
    requests.

    :param dict1:
    :param dict2:
    :return: dict1 reference with updated value.
    """
    for k in dict2:
        if k in dict1 and isinstance(dict1[k], dict) and isinstance(dict2[k], dict):
            merge(dict1[k], dict2[k])
        else:
            dict1[k] = dict2[k]
    return dict1


def to_camel_case(snake_str):
    components = snake_str.split('_')
    # We capitalize the first letter of each component except the first one
    # with the 'title' method and join them together.
    return components[0].lower() + ''.join(x.title() for x in components[1:])


def safe_convert(value, type_, operation=None):
    if value is None:
        return value
    key = None
    if operation:
        key = get_task_name(operation)
        if value is not None:
            if isinstance(value, str) and value.strip().startswith('{') and value.strip().endswith('}'):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    pass
    if isinstance(value, dict):
        if key in value:
            value = value[key]
        elif type_ and type_ != dict:
            return None
        else:
            found = [x for x in ALERTERS_TASK_BY_OPERATION.values() if x in value]
            if found:
                # Found the other operation
                return None
    if type_ is not None and not isinstance(value, type_):
        try:
            if type_ in (dict, list):
                value = json.loads(str(value))
            elif type_ == bool:
                return str(value).lower() in ('true', 'y', 's', 'yes', 'si', 'sí')
            else:
                return type_(str(value))
        except Exception as e:  # noqa
            if type_ == list:
                return [x.strip() for x in str(value).split(',')]
            logger.warning("Cannot convert '%s' to '%s'", str(value), type_.__name__)
            return None

    return value


class ConfigKeyDict(MutableMapping):
    """
    A dictionary whose keys can be requested in camel case or snake case.
    It removes '_'. '-', '.' and is case insensitive

    *the_var*, *THE_VAR*, *THEVAR*, *thevar*, *TheVar*, *thevar*... correspond to the same dict entry.
    """

    def __init__(self, *args, **kwargs):
        self.store = dict()
        self.keys_store = dict()
        self.update(dict(*args, **kwargs))  # use the free update to set keys

    def __getitem__(self, key):
        return self.store[self._key_transform(key)]

    def __setitem__(self, key, value):
        new_key = self._key_transform(key)
        self.store[new_key] = value
        if new_key not in self.keys_store:
            self.keys_store[new_key] = key

    def __delitem__(self, key):
        new_key = self._key_transform(key)
        del self.store[new_key]
        del self.keys_store[new_key]

    def __contains__(self, key):
        new_key = self._key_transform(key)
        return new_key in self.store

    def __iter__(self):
        return iter(self.store)

    def __len__(self):
        return len(self.store)

    def __repr__(self):
        return self.store.__repr__()

    def __str__(self):
        return self.store.__str__()

    @staticmethod
    def _key_transform(key):
        if isinstance(key, str):
            return key.replace('_', '').replace('-', '').replace('.', '').replace(' ', '').lower()
        return key

    def get_for_operation(self, key, operation, default=None):
        if operation:
            oper_key = get_task_name(operation)
            if not key.startswith(oper_key):
                return self.get(f"{oper_key}{key}", self.get(key, default=default))
        return self.get(key, default=default)

    def original_key(self, key):
        new_key = self._key_transform(key)
        return self.keys_store.get(new_key)


class ConfigurationContext(str, Enum):
    AlertEventTag = 'alert_event_tag'
    AlertAttribute = 'alert_attribute'
    AlerterConfig = 'alerter_config'
    AlerterGlobalConfig = 'alerter_global'
    GlobalConfig = 'global'
    DefaultValue = 'default'
    NotFound = 'not_found'


@dataclass
class VarDefinition:
    var_name: str
    default: Any = None
    specific_event_tag: str = None
    var_type: type = None
    renderable = True


class GlobalAttributes:
    """
    Attributes that will never depend on the alerter so no specific value for an alerter might be configured.

    It is possible to configure a default value for these attributes as a configuration property.
    """

    __slots__ = ()
    ALERTERS = VarDefinition('alerters', default=[])
    """
    Alert attribute with the list of alerters to notify to.
    """

    EVENT_TAGS = VarDefinition('eventTags', {})
    """
    Alert attribute with a dictionary of event tags configured for an alert.
    """

    AUTO_CLOSE_AT = VarDefinition('autoCloseAt', default=None, var_type=datetime)
    """
    Instant where alert must change its status to 'Closed'.
    """

    AUTO_CLOSE_AFTER = VarDefinition('autoCloseAfter', default=None, var_type=float)
    """
    Seconds from the last time an alert is received when it must change its status to 'Closed'.
    
    If this attribute is provided, attribute GlobalAttributes.AUTO_CLOSE_AT will be filled or replaced with the
    instant resulting of adding this value to the time when the alert was received.
    """


class ContextualConfiguration(object):
    """
    Class to manage contextual configuration.

    Values are read from alert and application configuration in steps in the order below.

    If the value is a dict, all steps are merged with priority from up to down.
    If it is not a dict, the value is the return of the first step that provides a non-null value.

    Variable names are not case-sensitive. CamelCase and snake_case formats are also considered the same
    (*the_var*, *THE_VAR*, *THEVAR*, *thevar*, *TheVar*, *thevar*... correspond to the same variable).

    Steps order:
      1. From event tags. Several tags are checked in order. Only the first one with a value is considered:
           - alert.attributes['eventTags'][<SPECIFIC_EVENT_TAG>]
           - alert.attributes['eventTags'][<ALERTER_NAME>_<VAR_NAME>]
           - alert.attributes['eventTags'][<VAR_NAME>]
      2. From attributes:
           - alert.attributes[<ALERTER_NAME>_CONFIG][<VAR_NAME>]
           - alert.attributes[<ALERTER_NAME>_<VAR_NAME>]
           - alert.attributes[<VAR_NAME>]
      3. From alerter configuration:
           - config[<ALERTER_NAME>_CONFIG[<VAR_NAME>]]
      4. From alerter configuration as KEY:
           - config[<ALERTER_NAME>_<VAR_NAME>]
      5. From default alerters configuration:
           - environ[ALERTERS_DEFAULT_<VAR_NAME>]
           - config[ALERTERS_DEFAULT_<VAR_NAME>]
      6. From default value if provided.

    If the value obtained if a dict and an operation is provided, returned value will be the one
    related to the operation. The keys for the dictionary should be the values of ALERTERS_TASK_BY_OPERATION
    for each operation.
    """

    #
    # Common configuration keys
    #
    ACTION_DELAY = VarDefinition('actionDelay', 180.0, 'START_ACTION_DELAY_SECONDS')
    """
    Delay to start processing a new event from the moment it is created, with a minimum of 10 seconds.
    Actual delay will be from -5 to +5 secs from the given delay.
    """

    IGNORE_RECOVERY = VarDefinition('ignoreRecovery', False)
    """
    If true, process_recovery is not executed
    """

    TASKS_DEFINITION = VarDefinition('TASKS_DEFINITION', {
        ALERTERS_TASK_BY_OPERATION['process_event']: {'queue': 'alert', 'priority': 1, 'retry_spec': {
            'max_retries': 32,
            'exponential': True,
            'interval_first': 2.0,  # First retry after 2 secs
            'interval_step': 5.0,  # Only for exponential = false
            'interval_max': 10.0 * 60,  # Max interval 10 min
            'jitter': False  # If true, random seconds between 0 and exponential calculated time
        }},
        ALERTERS_TASK_BY_OPERATION['process_recovery']: {'queue': 'recovery', 'priority': 6, 'retry_spec': {
            'max_retries': 16,
            'exponential': True,
            'interval_first': 2.0,  # First retry after 10 secs
            'interval_step': 5.0,  # Only for exponential = false
            'interval_max': 10.0 * 60,  # Max interval 10 min
            'jitter': False  # If true, random seconds between 0 and exponential calculated time
        }},
        ALERTERS_TASK_BY_OPERATION['process_repeat']: {'queue': 'repeat', 'priority': 7, 'retry_spec': {
            'max_retries': 2,
            'exponential': True,
            'interval_first': 2.0,  # First retry after 2 secs
            'interval_step': 5.0,  # Only for exponential = false
            'interval_max': 10.0 * 60,  # Max interval 10 min
            'jitter': True  # If true, random seconds between 0 and exponential calculated time
        }}
    })
    """
    Definition of task execution for the alert. Dict with the keys:
        - queue (str): Name of the queue that will process the operation
        - priority (int): Priority for the task (0 highest priority, 9 lowest priority)
        - retry_spec (dict): Specification of the mechanism for retries
            - max_retries (int): Maximum number of retries 
            - exponential (bool): If False, interval between two retries is calculated exponentially
            - interval_first (float): First interval
            - interval_step (float): Additional interval between two retries (only used if exponential is False)
            - interval_max (float): Maximum interval between two retries
            - jitter (bool): If true, retry will be executed in a random instant between 0 and the calculated interval
            
    Interval calculation:
        - If exponential is True: interval = min(interval_max, interval_first * (2 ** <retries>))
        - If exponential is False: interval = min(interval_max, interval_first + interval_step * <retries>)
        
        In both cases, if jitter is True, the actual interval will be a random instant between 0 
        and the interval calculated with the previous formula.
    """

    REPEAT_MIN_INTERVAL = VarDefinition('REPEAT_MIN_INTERVAL', 0.0)
    """
    Minimum interval after last processing init time to send a repeat event.
    """

    STORE_TRACEBACK_ON_EXCEPTION = VarDefinition('STORE_TRACEBACK_ON_EXCEPTION', False)
    """
    If True, stores the exception traceback in the alerter result attribute
    """

    @staticmethod
    def get_contextual_global_config(var_definition: VarDefinition, alert,
                                     plugin, operation=None) -> Tuple[Any, ConfigurationContext]:
        """
        Gets the configuration for a var definition provided as a tuple of name and default value.
        Use this method to query value of global keys.

        Values will be searched in alert attributes and global configuration properties.

        :param var_definition: Definition of the configuration attribute to query
        :param alerta.models.alert.Alert alert:
        :param iometrics_alerta.plugins.iom_plugin.IOMAlerterPlugin plugin:
        :param str operation:
        :return: configuration value and context where it was found
        """
        return ContextualConfiguration.get_contextual_config_generic(
            var_name=var_definition.var_name, alert=alert, alerter_name=plugin.alerter_name,
            operation=operation, type_=var_definition.var_type, default=var_definition.default,
            specific_event_tag=var_definition.specific_event_tag,
            global_config=plugin.global_app_config, alerter_config=plugin.alerter_config,
            renderable=var_definition.renderable)

    @staticmethod
    def get_contextual_alerter_config(var_definition: VarDefinition, alert,
                                      alerter, operation=None) -> Tuple[Any, ConfigurationContext]:
        """
        Gets the configuration for a var definition provided as a tuple of name and default value.
        Use this method to query value of alerter keys.

        Values will be searched in alert attributes and specific alerter configuration.

        :param var_definition: Definition of the configuration attribute to query
        :param alerta.models.alert.Alert alert:
        :param iometrics_alerta.plugins.Alerter alerter:
        :param str operation:
        :return: configuration value and context where it was found
        """
        return ContextualConfiguration.get_contextual_config_generic(
            var_name=var_definition.var_name, alert=alert, alerter_name=alerter.name,
            operation=operation, type_=var_definition.var_type, default=var_definition.default,
            specific_event_tag=var_definition.specific_event_tag,
            alerter_config=alerter.config, renderable=var_definition.renderable)

    @staticmethod
    def get_global_attribute_value(var_definition: VarDefinition, alert,
                                   operation=None, global_config=None) -> Any:
        """

        :param var_definition:
        :param alert:
        :param operation:
        :param global_config: Check for value in this config if not available as attribute
        :return:
        """
        return ContextualConfiguration.get_contextual_config_generic(
            var_name=var_definition.var_name, alert=alert, alerter_name='',
            operation=operation, type_=var_definition.var_type, default=var_definition.default,
            specific_event_tag=var_definition.specific_event_tag,
            alerter_config=None, global_config=global_config,
            renderable=var_definition.renderable)[0]

    @staticmethod
    def get_event_tags(alert, operation=None):
        key_name = GlobalAttributes.EVENT_TAGS.var_name
        alert_attributes = ConfigKeyDict(alert.attributes)
        config_attributes = ConfigKeyDict(flask.current_app.config)
        alert_event_tags = ConfigKeyDict(safe_convert(alert_attributes.get(key_name, {}), dict))
        if operation and operation in alert_event_tags:
            alert_event_tags = alert_event_tags[operation]
        config_event_tags = ConfigKeyDict(safe_convert(config_attributes.get(key_name, {}), dict))
        if operation and operation in config_event_tags:
            config_event_tags = config_event_tags[operation]
        return ConfigKeyDict({**config_event_tags, **alert_event_tags})

    @staticmethod
    def get_contextual_config_generic(var_name: str, alert, alerter_name: str, operation=None,
                                      type_=None, default=None,
                                      specific_event_tag: str = None, alerter_config: dict = None,
                                      global_config: dict = None, renderable=True) -> Tuple[Any, ConfigurationContext]:
        """
        Read a configuration not available as class constant. Therefore, the name of the var, default value and/or type
        must be provided as parameters.

        :param var_name:
        :param alert:
        :param alerter_name:
        :param str operation:
        :param alerter_config:
        :param global_config:
        :param type_:
        :param default:
        :param specific_event_tag:
        :param renderable:
        :return: configuration value and context where it was found
        """
        if global_config is None:
            global_config = {}
        if alerter_config is None:
            alerter_config = {}
        level = None
        if default is not None:
            default = safe_convert(default, type_, operation)
            type_ = type(default)
        is_dict = isinstance(default, dict) if default is not None else None
        if is_dict is None:
            is_dict = type_ == dict if type_ is not None else None

        alert_attributes = ConfigKeyDict(alert.attributes)
        alerter_config = ConfigKeyDict(alerter_config)

        # From event tags attribute. if specific_event_tag is provided, check first.
        # First try with the prefix of the operation ('new' or 'recovery') if tag name doesn't start with that prefix.
        # For dict vars, only the first tag found is used. If both tags have data, data is not merged.
        event_tags = ContextualConfiguration.get_event_tags(alert, operation)
        tag_list = {t for t in (specific_event_tag, alerter_name+var_name, var_name) if t}
        for t in tag_list:
            from_tags = safe_convert(event_tags.get_for_operation(t, operation), type_, operation)
            if from_tags is not None:
                level = ConfigurationContext.AlertEventTag
                if is_dict is None:
                    is_dict = isinstance(from_tags, dict)
                if not is_dict:
                    if renderable:
                        from_tags = render_value(from_tags, alert=alert, config=alerter_config,
                                                 attributes=alert_attributes, event_tags=event_tags)
                    return from_tags, level
                break
        else:
            from_tags = None

        # From attributes
        if alerter_name:
            alerter_attributes_dict_var = alerter_name+ALERTER_SPECIFIC_CONFIG_KEY_SUFFIX
            alert_alerter_attributes = ConfigKeyDict(safe_convert(
                alert_attributes.get_for_operation(alerter_attributes_dict_var, operation, {}),
                dict, operation))
            from_attr = safe_convert(alert_alerter_attributes.get_for_operation(var_name, operation), type_, operation)
        else:
            from_attr = None
        if from_attr is None:
            var_names = alerter_name+var_name, var_name
            for name in set(var_names):
                from_attr = safe_convert(alert_attributes.get_for_operation(name, operation), type_, operation)
                if from_attr is not None:
                    break
        if from_attr is not None:
            if level is None:
                level = ConfigurationContext.AlertAttribute
            if is_dict is None:
                is_dict = isinstance(from_attr, dict)
            if not is_dict:
                if renderable:
                    from_attr = render_value(from_attr, alert=alert, config=alerter_config,
                                             attributes=alert_attributes, event_tags=event_tags)
                return from_attr, level

        # From alerter specific configuration as env var o in global config: <ALERTER_NAME>_CONFIG[<var>]
        from_config_alerter = safe_convert(alerter_config.get_for_operation(var_name, operation), type_, operation)
        if from_config_alerter is not None:
            if level is None:
                level = ConfigurationContext.AlerterConfig
            if is_dict is None:
                is_dict = isinstance(from_config_alerter, dict)
            if not is_dict:
                if renderable:
                    from_config_alerter = render_value(from_config_alerter, alert=alert, config=alerter_config,
                                                       attributes=alert_attributes, event_tags=event_tags)
                return from_config_alerter, level

        # From alerter global configuration: <ALERTER_NAME>_<VAR>
        environ = ConfigKeyDict(os.environ)
        global_config = ConfigKeyDict(global_config)
        alerter_key = f"{alerter_name}{var_name}"
        from_global_alerter = safe_convert(environ.get(alerter_key,
                                                       global_config.get_for_operation(alerter_key, operation)),
                                           type_, operation)
        if from_global_alerter is not None:
            if level is None:
                level = ConfigurationContext.AlerterGlobalConfig
            if is_dict is None:
                is_dict = isinstance(from_global_alerter, dict)
            if not is_dict:
                if renderable:
                    from_global_alerter = render_value(from_global_alerter, alert=alert, config=alerter_config,
                                                       attributes=alert_attributes, event_tags=event_tags)
                return from_global_alerter, level

        # From default alerters configuration as env var o in global config: ALERTERS_DEFAULT_<VAR>
        default_key = f"{ALERTER_DEFAULT_CONFIG_VALUE_PREFIX}{var_name}"
        from_config_default = safe_convert(environ.get(default_key,
                                                       global_config.get_for_operation(default_key, operation)),
                                           type_, operation)
        if from_config_default is not None:
            if level is None:
                level = ConfigurationContext.GlobalConfig
            if is_dict is None:
                is_dict = isinstance(from_config_default, dict)
            if not is_dict:
                if renderable:
                    from_config_default = render_value(from_config_default, alert=alert, config=alerter_config,
                                                       attributes=alert_attributes, event_tags=event_tags)
                return from_config_default, level

        if level is None:
            level = ConfigurationContext.DefaultValue if default is not None \
                else ConfigurationContext.NotFound

        if is_dict:
            prio0 = {**default} if default is not None else {}
            prio1 = {**from_config_default} if from_config_default is not None else {}
            prio2 = {**from_global_alerter} if from_global_alerter is not None else {}
            prio3 = {**from_config_alerter} if from_config_alerter is not None else {}
            prio4 = {**from_attr} if from_attr is not None else {}
            prio5 = {**from_tags} if from_tags is not None else {}
            result = merge(prio0,
                           merge(prio1,
                                 merge(prio2,
                                       merge(prio3,
                                             merge(prio4, prio5)))))
            if renderable:
                result = render_value(result, alert=alert, config=alerter_config,
                                      attributes=alert_attributes, event_tags=event_tags)
            return result, level
        else:
            if default and renderable:
                default = render_value(default, alert=alert, config=alerter_config,
                                       attributes=alert_attributes, event_tags=event_tags)
            return default, level


def init_configuration(config):
    overridable_keys = (
        'ALERTERS_TASK_BY_OPERATION',
        'ALERTERS_TEMPLATES_LOCATION'
    )
    for key in overridable_keys:
        if key in config:
            current = globals()[key]
            new = config[key]
            if isinstance(current, dict) and isinstance(new, dict):
                current.update(new)
            else:
                globals()[key] = new


def init_jinja_loader(app):
    with app.app_context():
        my_loader = jinja2.ChoiceLoader([
            app.jinja_loader,
            jinja2.FileSystemLoader(ALERTERS_TEMPLATES_LOCATION),
        ])
        app.jinja_loader = my_loader
        app.json_encoder = CustomJSONEncoder
