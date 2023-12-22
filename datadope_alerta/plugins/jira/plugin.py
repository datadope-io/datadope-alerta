import json
import os
from typing import Type, Optional, Tuple, Dict, Any

# noinspection PyPackageRequirements
import yaml

from alerta.models.alert import Alert
from datadope_alerta import NormalizedDictView, get_config, VarDefinition, ContextualConfiguration, GlobalAttributes
from datadope_alerta.plugins import Alerter, getLogger, RetryableException
from datadope_alerta.plugins.iom_plugin import IOMAlerterPlugin
from datadope_alerta.plugins.jira.client import JiraClient, RequestFields

CONFIG_FILE_KEY = 'JIRA_CONFIG_FILE'
DEFAULT_CONFIG_FILE = 'config.yaml'

JIRA_ID_NOT_APPLY = 'JIRA_ID_NOT_APPLY'

logger = getLogger(__name__)

class ConfigurationFields:
    __slots__ = ()

    WEB_ISSUE_URL = "web_issue_url"

    class DictFields:
        __slots__ = ()

        CONNECTION = "connection"
        DATA = "data"
        MAPPINGS = "mappings"
        OPERATION_CREATE = "operation_create"
        OPERATION_RESOLVE = "operation_resolve"
        OPERATION_REPEAT = "operation_repeat"
        OPERATION_CLOSE = "operation_close"


class ResultFields:
    __slots__ = ()

    JIRA_ID = "jira_id"
    JIRA_KEY = "jira_key"
    REASON = "reason"
    RESPONSE = "response"



class JiraAlerter(Alerter):

    _default_config = None

    def __init__(self, name, bgtask=None):
        super().__init__(name, bgtask)
        config_fields = [NormalizedDictView.key_transform(y) for x, y in vars(ConfigurationFields.DictFields).items()
                         if not x.startswith('_')]
        for k, v in self.config.items():
            if NormalizedDictView.key_transform(k) in config_fields and isinstance(v, str):
                self.config[k] = json.loads(v)
        self.jira_client = JiraClient(**self.config.get(ConfigurationFields.DictFields.CONNECTION, {}))

    @staticmethod
    def read_default_configuration():
        conf_file = get_config(key=CONFIG_FILE_KEY, default=os.path.join(os.path.dirname(__file__),
                                                                         DEFAULT_CONFIG_FILE))
        with open(conf_file, 'r') as f:
            return yaml.safe_load(f.read())

    @classmethod
    def get_default_configuration(cls) -> dict:
        if cls._default_config is None:
            cls._default_config = cls.read_default_configuration()
        return cls._default_config

    def process_event(self, alert: 'Alert', reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        operation = Alerter.process_event.__name__
        operation_field = ConfigurationFields.DictFields.OPERATION_CREATE
        response = self._process_operation(alert, operation_field, operation, reason)
        if response.status_code in (200, 201):
            response_data = response.json()
            jira_id = response_data['id']
            jira_key = response_data['key']
            jira_link = self.config.get(ConfigurationFields.WEB_ISSUE_URL)
            if jira_link:
                jira_link = self.render_value(value=jira_link, alert=alert, jira_id=jira_id, jira_key=jira_key)
                if jira_link.startswith('http'):
                    jira_link = f"<a href=\"{jira_link}\">{jira_key}</a>"
            else:
                jira_link = jira_key
            alert.update_attributes({
                'jiraId': jira_id,
                'jiraKey': jira_key,
                'jiraLink': jira_link
            })
            return True, {
                ResultFields.JIRA_ID: jira_id,
                ResultFields.JIRA_KEY: jira_key,
                ResultFields.RESPONSE: response_data
            }
        # FIXME: handle errors - maybe retry?
        short_error = f"ERROR: {response.status_code}"
        alert.update_attributes({
            'jiraId': short_error,
            'jiraKey': short_error,
            'jiraLink': short_error
        })
        try:
            data = response.json()
        except Exception:  # noqa
            data = response.text
        msg = f"Create issue response received with status {response.status_code}. Content: {data}"
        logger.warning("%s", msg)
        if response.status_code in (401, 403) or not isinstance(data, dict):
            raise RetryableException(msg)
        return False, self.failure_response(
            reason='JIRA_ERROR',
            message=f"Response status: {response.status_code}",
            extra_info=data
        )

    def process_recovery(self, alert: 'Alert', reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        # Event closed in Alerta => close in Jira
        operation = Alerter.process_recovery.__name__
        operation_field = ConfigurationFields.DictFields.OPERATION_CLOSE
        return self._process_update(alert, operation, reason, operation_field)

    def process_repeat(self, alert: 'Alert', reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        operation = Alerter.process_repeat.__name__
        operation_field = ConfigurationFields.DictFields.OPERATION_REPEAT
        return self._process_update(alert, operation, reason, operation_field)

    def process_action(self, alert: 'Alert', reason: Optional[str], action: str) -> Tuple[bool, Dict[str, Any]]:
        operation = Alerter.process_action.__name__
        if action == ContextualConfiguration.get_global_configuration(
                GlobalAttributes.CONDITION_RESOLVED_ACTION_NAME):
            ignore_recovery, level = self.get_contextual_configuration(ContextualConfiguration.IGNORE_RECOVERY,
                                                                       alert=alert,
                                                                       operation=Alerter.process_recovery.__name__)
            if ignore_recovery:
                logger.info("Ignoring resolve configured with context '%s'", level.value)
                result_data = {"info": {"message": "IGNORED RECOVERY"}}
                return True, result_data
            operation_field = ConfigurationFields.DictFields.OPERATION_RESOLVE
            return self._process_update(alert, operation, reason, operation_field)
        return True, {}

    def _process_operation(self, alert, operation_field, operation, reason, **kwargs):
        message = self.get_message(alert, operation=operation, reason=reason)
        data, _ = self.get_contextual_configuration(VarDefinition(ConfigurationFields.DictFields.DATA,
                                                                  default={},
                                                                  var_type=dict,
                                                                  renderable=False),
                                                    alert=alert,
                                                    operation=operation)
        data = self.render_value(value=data, alert=alert, operation=operation, message=message, reason=reason, **kwargs)
        mappings, _ = self.get_contextual_configuration(VarDefinition(ConfigurationFields.DictFields.MAPPINGS,
                                                                      default={},
                                                                      var_type=dict),
                                                        alert=alert,
                                                        operation=operation)
        operation_data = self.render_value(value=self.config[operation_field],
                                           alert=alert, operation=operation,
                                           message=message,
                                           reason=reason,
                                           data=NormalizedDictView(data),
                                           mappings=NormalizedDictView(mappings),
                                           **kwargs)
        dry_run = self.is_dry_run(alert, operation)
        if dry_run:
            logger.info("DRY RUN: not sending alert to Jira at %s. Payload:\n%s",
                        self.jira_client.base_url, json.dumps(operation_data.get(RequestFields.PAYLOAD), indent=2))
            alert.update_attributes({
                'jiraId': JIRA_ID_NOT_APPLY,
                'jiraKey': JIRA_ID_NOT_APPLY,
                'jiraLink': JIRA_ID_NOT_APPLY
            })
            return True, {ResultFields.JIRA_ID: JIRA_ID_NOT_APPLY, ResultFields.REASON: "dry_run"}
        logger.info("Connecting to Jira at: '%s'", self.jira_client.base_url)
        return self.jira_client.request(**operation_data)

    def _process_update(self, alert, operation, reason, operation_field):
        jira_id, jira_key = self._preprocess_update(alert)
        if not isinstance(jira_id, str):
            return jira_id, jira_key
        response = self._process_operation(alert, operation_field, operation, reason,
                                           jira_id=jira_id, jira_key=jira_key)
        if response.status_code in (200, 201, 204):
            response_data = response.json() if response.status_code != 204 else {"status_code": 204}
            return True, {ResultFields.RESPONSE: response_data}
        # FIXME: handle errors - maybe retry?
        try:
            data = response.json()
        except Exception:  # noqa
            data = response.text
        msg = f"Jira update response received with status {response.status_code}. Content: {data}"
        logger.warning("%s", msg)
        if response.status_code in (401, 403) or not isinstance(data, dict):
            raise RetryableException(msg)
        return False, self.failure_response(
            reason='JIRA_UPDATE_ERROR',
            message=f"Response status: {response.status_code}",
            extra_info=data
        )

    def _preprocess_update(self, alert) -> Tuple[bool | str, Dict[str, Any] | str]:
        create_data = self.get_operation_result_data(alert, Alerter.process_event.__name__)
        if not create_data:
            logger.warning("Requested update of a non-alerted event. Unexpected state")
            return False, self.failure_response(
                reason='Event not created',
                message=f"Requested update of a non-alerted event. Unexpected state"
            )
        jira_id = create_data.get(ResultFields.JIRA_ID)
        jira_key = create_data.get(ResultFields.JIRA_KEY)
        if not jira_id or jira_id.startswith('ERROR:'):
            logger.warning("Jira ID not stored in new event result data")
            return False, self.failure_response(
                reason='No Jira ID',
                message=f"Jira ID not stored in new event result data"
            )
        if jira_id == JIRA_ID_NOT_APPLY:
            logger.info("Updating alert that doesn't open issue in Jira")
            return True, {
                ResultFields.RESPONSE: {},
                ResultFields.REASON: "Jira ID is N/A"
            }
        return jira_id, jira_key


class JiraPlugin(IOMAlerterPlugin):

    def get_alerter_class(self) -> Type[Alerter]:
        return JiraAlerter

