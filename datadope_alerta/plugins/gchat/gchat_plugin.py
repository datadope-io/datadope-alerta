import os
import re
from typing import Optional, Tuple, Dict, Any
import requests
# noinspection PyPackageRequirements
import yaml

from alerta.models.alert import Alert
from datadope_alerta import get_config, VarDefinition, ConfigurationContext
from datadope_alerta.plugins import getLogger
from datadope_alerta.plugins.iom_plugin import Alerter, IOMAlerterPlugin

CONFIG_FILE_KEY = 'GCHAT_CONFIG_FILE'  # noqa
DEFAULT_CONFIG_FILE = 'config.yaml'

GOOGLE_CHAT_URL_REGEX = 'https://chat.googleapis.com/v1/spaces/.+?'

logger = getLogger(__name__)


class GChatAlerter(Alerter):
    _config = None

    @staticmethod
    def _read_default_configuration():
        conf_file = get_config(key=CONFIG_FILE_KEY, default=os.path.join(os.path.dirname(__file__),
                                                                         DEFAULT_CONFIG_FILE))
        with open(conf_file, 'r') as f:
            return yaml.safe_load(f.read())

    @classmethod
    def get_default_configuration(cls) -> dict:
        if cls._config is None:
            cls._config = cls._read_default_configuration()
        return cls._config

    def process_event(self, alert: Alert, reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        return self._process_alert(Alerter.process_event.__name__, alert, reason)

    def process_recovery(self, alert: Alert, reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        return self._process_alert(Alerter.process_recovery.__name__, alert, reason)

    def process_repeat(self, alert: Alert, reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        return True, {}

    def process_action(self, alert: Alert, reason: Optional[str], action: str) -> Tuple[bool, Dict[str, Any]]:
        return super().process_action(alert, reason, action)

    def _process_alert(self, operation, alert: Alert, reason):
        trigger_severity = alert.severity
        alert_type = alert.event_type
        event_title, event_title_context = \
            self.get_contextual_configuration(VarDefinition('ALERTER_TITLE', var_type=str), alert, operation)
        event_subtitle = None

        alert_logos, _ = self.get_contextual_configuration(
            VarDefinition('ALERTER_LOGOS', var_type=dict), alert, operation)

        if event_title_context and event_title_context == ConfigurationContext.AlerterConfig:
            if operation and operation == Alerter.process_recovery.__name__:
                event_subtitle = "Alert Recovery"
                trigger_severity = 'ok'
            else:
                event_subtitle = "New Alert Received"

        event_logo = alert_logos[alert_type][trigger_severity] if \
            alert_type in alert_logos else alert_logos['iometrics'][trigger_severity]

        event_time = alert.create_time.strftime('%d/%m/%Y, %H:%M:%S')

        chats_list, _ = self.get_contextual_configuration(VarDefinition('GCHAT'), alert, operation)
        response = None
        try:
            chats_list = self._get_gchat_chats(chats_list)
            message_icons = self._config['message_icons']
            template = self._config['cards_template']
            message_text = self.get_message(alert, operation, reason)
            event_message = self.render_value(template, alert, operation, event_logo=event_logo,
                                              message_icons=message_icons,
                                              event_time=event_time, event_title=event_title,
                                              event_subtitle=event_subtitle, message_text=message_text)
            if chats_list and event_message:
                for idy, chat_url in enumerate(chats_list):
                    response = self._send_message_to_gchat(chat_url, event_message)
                    if response and response.status_code in (200, 201):
                        logger.info("GChat %s notified successfully", str(chat_url))
                    else:
                        logger.warning("Could not notify GChat: %s", str(chat_url))
            else:
                logger.warning("Could not notify any chat, no chats provided")
        except Exception as e:
            logger.exception("UNHANDLED EXCEPTION: %s", str(e))
            raise
        return (True, {}) if (response and response.status_code in (200, 201)) else (False, {})

    @staticmethod
    def _get_gchat_chats(gchat_tag):
        chats_lists = set()
        if gchat_tag:
            if isinstance(gchat_tag, list):
                gchats = ''
                for chat in gchat_tag:
                    gchats = gchats.join(f'{chat},')
                gchat_tag = gchats
            chats = [x.strip() for x in gchat_tag.split(',')]
            for chat in chats:
                if re.search(GOOGLE_CHAT_URL_REGEX, chat):
                    chats_lists.add(chat)
                else:
                    logger.warning("Invalid gchat %s. Please use id_ prefix or direct url" % chat)
        else:
            logger.warning("No 'GCHAT' tag recieved")

        return chats_lists

    @staticmethod
    def _send_message_to_gchat(chat_url, message):
        try:
            logger.info("REQUEST SEND GCHAT MESSAGE; chat: '{}', message: '{}'".format(chat_url, message))
            response = requests.post(chat_url, json=message, proxies={})
        except Exception as e:
            logger.warning("ERROR sending information to Google Chat: {}".format(str(e)))
            raise

        return response


class GChatPlugin(IOMAlerterPlugin):

    def get_alerter_class(self):
        return GChatAlerter
