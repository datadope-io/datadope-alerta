from typing import Optional, Tuple, Dict, Any

# noinspection PyPackageRequirements
from pyzabbix import ZabbixAPI

from alerta.models.alert import Alert
from alerta.plugins import PluginBase
from datadope_alerta import ContextualConfiguration, safe_convert, NormalizedDictView, GlobalAttributes, \
    thread_local
from datadope_alerta.backend.flexiblededup.models.external_references import ExternalReferences
from datadope_alerta.plugins import Alerter, getLogger
from datadope_alerta.plugins.iom_plugin import IOMAlerterPlugin

PLATFORM_REFERENCES_ATTRIBUTE_SUFFIX = 'References'

logger = getLogger(__name__)

class ConfigurationFields:
    __slots__ = ()

    PLATFORM_FIELD = 'platform_field'
    """
    Alert field or attribute to use a the platform
    """
    SUPPORTED_PLATFORMS = 'supported_platforms'
    REFERENCE_ATTRIBUTES_SUFFIX = 'reference_attributes'
    CONNECTION_SUFFIX = 'connection'

    class ConnectionFields:
        __slots__ = ()
        URL = 'url'
        API_TOKEN = 'api_token'
        """
        If provided, api token method will be used for auth. User and password, if provided, will be ignored.
        """
        USER = 'user'
        """
        Not used if api_token is provided. Mandatory if api_token is not provided.
        """
        PASSWORD = 'password'
        """
        Not used if api_token is provided. Mandatory if api_token is not provided.
        """
        VERIFY_SSL = 'verify_ssl'
        TIMEOUT = 'timeout'


class ZabbixAlerter(Alerter):

    # noinspection PyUnusedLocal
    def __init__(self, name, bgtask=None):
        super().__init__('zabbix', bgtask)  # Force name to 'zabbix'
        self.platform_attribute = self.config[ConfigurationFields.PLATFORM_FIELD]
        self.supported_platforms = [x.lower() for x in safe_convert(
            self.config[ConfigurationFields.SUPPORTED_PLATFORMS], type_=list)]

    @classmethod
    def get_default_configuration(cls) -> dict:
        default_platform = 'zabbix'
        return {
            ConfigurationFields.PLATFORM_FIELD: 'origin',
            ConfigurationFields.SUPPORTED_PLATFORMS: [default_platform],
            f"{default_platform}_{ConfigurationFields.REFERENCE_ATTRIBUTES_SUFFIX}":  [
                'zabbixEventId',
                'eventId'
            ],
            f"{default_platform}_{ConfigurationFields.CONNECTION_SUFFIX}":  {
                ConfigurationFields.ConnectionFields.URL: 'the url',
                # ConfigurationFields.ConnectionFields.API_TOKEN: 'the api token', Allow not receiving it to use user
                ConfigurationFields.ConnectionFields.USER: 'the user',
                ConfigurationFields.ConnectionFields.PASSWORD: 'the pass',
                ConfigurationFields.ConnectionFields.VERIFY_SSL: True,
                ConfigurationFields.ConnectionFields.TIMEOUT: 12.1
            }
        }

    def process_event(self, alert: 'Alert', reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        return True, {}

    def process_repeat(self, alert: 'Alert', reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        return True, {}

    def process_action(self, alert: 'Alert', reason: Optional[str], action: str) -> Tuple[bool, Dict[str, Any]]:
        return True, {}

    def process_recovery(self, alert: 'Alert', reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        alerter_config = NormalizedDictView(self.get_alerter_config(self.name))
        alert_attributes = NormalizedDictView(alert.attributes)
        platform: str = getattr(alert, self.platform_attribute, alert_attributes.get(self.platform_attribute))
        if not platform:
            logger.debug("Platform field not filled. Ignoring recovery execution")
            return True, {}
        platform = platform.lower()
        if platform not in self.supported_platforms:
            logger.debug("Platform '%s' not supported by plugin. Ignoring recovery execution", platform)
            return True, {}
        model = ExternalReferences()
        events_to_close = model.get_references(alert.id, platform)
        messages = {}
        response = {
            'events_to_close': events_to_close,
            'result': messages
        }
        connection_config = NormalizedDictView(alerter_config[f"{platform}_{ConfigurationFields.CONNECTION_SUFFIX}"])
        success = True
        if events_to_close:
            url = connection_config.get(ConfigurationFields.ConnectionFields.URL)
            user = connection_config.get(ConfigurationFields.ConnectionFields.USER)
            password = connection_config.get(ConfigurationFields.ConnectionFields.PASSWORD)
            api_token = connection_config.get(ConfigurationFields.ConnectionFields.API_TOKEN)
            ssl_verify = str(connection_config.get(ConfigurationFields.ConnectionFields.VERIFY_SSL, True))\
                             .lower() not in ('false', 'no')
            try:
                timeout = float(connection_config.get(ConfigurationFields.ConnectionFields.TIMEOUT, 5.1))
            except:  # noqa
                timeout = 5.1
            if not api_token and (not user or not password):
                logger.warning("Missing some connection configuration for platform '%s'", platform)
                return False, self.failure_response(
                    reason='Wrong configuration',
                    message=f"Missing some connection configuration for platform '{platform}'")
            try:
                zapi = ZabbixAPI(url, timeout=timeout)
                if not ssl_verify:
                    zapi.session.verify = False
                if api_token:
                    zapi.login(api_token=api_token)
                else:
                    zapi.login(user=user, password=password)
                logger.debug("Connected to Zabbix API Version %s", zapi.version)
                # One by one: one may fail but the rest may work.
                for event_id in events_to_close:
                    try:
                        result = zapi.event.acknowledge(eventids=event_id,
                                                        action=1 + 4,  # close problem + add message
                                                        message=f"Alert '{alert.id}' closed in IOMetrics Alerta")
                        if str(event_id) in [str(x) for x in result.get("eventids", [])]:
                            messages[event_id] = "Closed"
                        else:
                            messages[event_id] = 'Not found'
                    except Exception as e:
                        messages[event_id] = str(e)
                        success = False
            except Exception as e:
                logger.warning("Exception login to Zabbix: %s", e)
                raise
        return success, response


class ZabbixBasePlugin(PluginBase):
    alerter_config = None
    platform_attribute = None
    supported_platforms = None

    def pre_receive(self, alert: Alert, **kwargs) -> Alert:
        # Ensure that zabbix alerter is included in alerters attribute if alert platform is supported by zabbix alerter
        thread_local.alert_id = alert.id
        thread_local.alerter_name = 'zabbix_base'
        try:
            if self.alerter_config is None:
                self.alerter_config = NormalizedDictView(ZabbixAlerter.get_alerter_config('zabbix',
                                                                                          do_not_cache=True))
                self.platform_attribute = self.alerter_config[ConfigurationFields.PLATFORM_FIELD]
                self.supported_platforms = [x.lower() for x in safe_convert(
                    self.alerter_config[ConfigurationFields.SUPPORTED_PLATFORMS], type_=list)]
            alert_attributes = NormalizedDictView(alert.attributes)
            platform: str = getattr(alert, self.platform_attribute, alert_attributes.get(self.platform_attribute))
            if platform:
                platform = platform.lower()
                if platform in self.supported_platforms:
                    alerters_key = GlobalAttributes.ALERTERS.var_name
                    alerters = ContextualConfiguration.get_global_attribute_value(
                        GlobalAttributes.ALERTERS, alert, global_config=kwargs['config']) or []
                    if 'zabbix' not in alerters:
                        alerters.append('zabbix')
                        alert_attributes = NormalizedDictView(alert.attributes)
                        alert_attributes[alerters_key] = alerters
            return alert
        finally:
            thread_local.alerter_name = None

    def post_receive(self, alert: 'Alert', **kwargs) -> Optional['Alert']:
        thread_local.alert_id = alert.id
        thread_local.alerter_name = 'zabbix_base'
        try:
            if self.alerter_config is None:
                self.alerter_config = NormalizedDictView(ZabbixAlerter.get_alerter_config('zabbix',
                                                                                          do_not_cache=True))
                self.platform_attribute = self.alerter_config[ConfigurationFields.PLATFORM_FIELD]
                self.supported_platforms = [x.lower() for x in safe_convert(
                    self.alerter_config[ConfigurationFields.SUPPORTED_PLATFORMS], type_=list)]
            # Add Zabbix reference to the alert id.
            alert_attributes = NormalizedDictView(alert.attributes)
            platform = getattr(alert, self.platform_attribute, alert_attributes.get(self.platform_attribute))
            if platform in self.supported_platforms:
                reference_fields = safe_convert(
                    self.alerter_config.get(f"{platform}_{ConfigurationFields.REFERENCE_ATTRIBUTES_SUFFIX}"),
                    type_=list)
                reference = None
                for f in reference_fields:
                    if f in alert_attributes:
                        reference = alert_attributes[f]
                        if reference:
                            break
                if reference:
                    model = ExternalReferences()
                    model.insert(alert.id, platform, reference)
                    alert_attributes[f"{platform}{PLATFORM_REFERENCES_ATTRIBUTE_SUFFIX}"] = \
                        model.get_references(alert.id, platform)
                    return alert
                else:
                    logger.warning("Alert from platform '%s' does not have any of the reference attributes (%s) filled",
                                   platform, ', '.join(reference_fields))

            return None
        finally:
            thread_local.alerter_name = None

    def status_change(self, alert: 'Alert', status: str, text: str, **kwargs) -> Any:
        return None


class ZabbixIOMPlugin(IOMAlerterPlugin):
    def get_alerter_class(self):
        return ZabbixAlerter
