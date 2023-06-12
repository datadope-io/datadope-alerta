from typing import Any, Optional

import requests

from datadope_alerta import ContextualConfiguration, VarDefinition
from datadope_alerta.plugins import getLogger

from alerta.models.alert import Alert
from alerta.plugins import PluginBase

logger = getLogger(__name__)

CONFIG_DEFAULT_PATH = 'config.yaml'

KEY_URL = 'cmdb_gateway_url'
KEY_API_KEY = 'cmdb_gateway_api_key'
KEY_VERIFY_SSL = 'cmdb_gateway_verify_ssl'

SECURITY_HEADER = 'X-IOMETRICS-API-KEY'

GET_INFO_PATH = '/misc/affected_services'
GET_INFO_PARAM = 'ci_code'


# noinspection SpellCheckingInspection
class CMDBContextPlugin(PluginBase):

    def __init__(self, name=None):
        super().__init__(name=name)

    def pre_receive(self, alert: 'Alert', **kwargs) -> 'Alert':
        base_url = ContextualConfiguration.get_global_configuration(VarDefinition(KEY_URL, var_type=str))
        api_key = ContextualConfiguration.get_global_configuration(VarDefinition(KEY_API_KEY, var_type=str))
        verify_ssl = \
            str(ContextualConfiguration.get_global_configuration(
                VarDefinition(KEY_VERIFY_SSL, var_type=str))).lower() in ('yes', 'true', 'sí', 'si')

        url = '/'.join(s.strip('/') for s in (base_url, GET_INFO_PATH))
        params = {GET_INFO_PARAM: alert.resource}
        headers = {SECURITY_HEADER: api_key}
        logger.info("CMDB INFO REQUEST WITH URL: %s", url)
        try:
            response = requests.get(url, params=params, headers=headers, verify=verify_ssl, timeout=(9.1, 60))
            if response.status_code == 200:
                resp_json = response.json()
                watchers = resp_json[alert.resource].get('watchers', [])
                if watchers:
                    alert_alerters = ContextualConfiguration.get_global_attribute_value(
                        VarDefinition('ALERTERS', var_type=list), alert)
                    send_to = ContextualConfiguration.get_global_attribute_value(VarDefinition('SENDTO', var_type=list),
                                                                                 alert)

                    if alert_alerters is not None:
                        if 'email' not in alert_alerters:
                            alert_alerters.append('email')
                    else:
                        alert.attributes['alerters'] = ['email']

                    if send_to is None:
                        send_to = watchers
                    else:
                        send_to.extend(watchers)

                    if send_to:
                        alert.attributes['sendTo'] = list(set(send_to))
                        alert.attributes['cmdbWatchers'] = set(watchers)
                        logger.warning("Watchers gotten from CMDB for CI %s", alert.resource)

                try:
                    data = resp_json.get(alert.resource)['data']
                    if data:
                        alert.attributes['cmdbFunctionalInformation'] = data
                        logger.warning("Functional info gotten from CMDB for CI %s", alert.resource)
                except KeyError:
                    logger.warning("Functional info not found for CI %s", alert.resource)

            elif response.status_code == 404:
                logger.warning("CI with code %s not found in CMDB", alert.resource)
            else:
                logger.warning("CMDB Status %s for CI %s, response: %s", response.status_code, False, alert.resource,
                               response.text)
        except Exception as e:  # noqa
            logger.warning("Exception getting data for ci %s in CMDB: %s", alert.resource, str(e))

        return alert

    def post_receive(self, alert: 'Alert', **kwargs) -> Optional['Alert']:
        return None

    def status_change(self, alert: 'Alert', status: str, text: str, **kwargs) -> Any:
        return None

    def take_action(self, alert: 'Alert', action: str, text: str, **kwargs) -> Any:
        return None

    def take_note(self, alert: 'Alert', text: Optional[str], **kwargs) -> Any:
        return None

    def delete(self, alert: 'Alert', **kwargs) -> bool:
        return True
