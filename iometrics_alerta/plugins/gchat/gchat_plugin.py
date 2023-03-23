import os
import re
import time
from typing import Optional, Tuple, Dict, Any
import requests
import yaml

from alerta.models.alert import Alert
from iometrics_alerta import get_config, VarDefinition, ConfigurationContext
from iometrics_alerta.plugins import getLogger
from iometrics_alerta.plugins.iom_plugin import Alerter, IOMAlerterPlugin

CONFIG_FILE_KEY = 'GCHAT_CONFIG_FILE'  # noqa
DEFAULT_CONFIG_FILE = 'config.yaml'

GOOGLE_CHAT_URL_REGEX = 'https://chat.googleapis.com/v1/spaces/.+?'

logger = getLogger(__name__)


class GChatAlerter(Alerter):
    _config = None

    @staticmethod
    def read_default_configuration():
        conf_file = get_config(key=CONFIG_FILE_KEY, default=os.path.join(os.path.dirname(__file__),
                                                                         DEFAULT_CONFIG_FILE))
        with open(conf_file, 'r') as f:
            return yaml.safe_load(f.read())

    @classmethod
    def get_default_configuration(cls) -> dict:
        if cls._config is None:
            cls._config = cls.read_default_configuration()
        return cls._config

    def process_event(self, alert: Alert, reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        return self._process_alert(Alerter.process_event.__name__, alert)

    def process_recovery(self, alert: Alert, reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        return self._process_alert(Alerter.process_recovery.__name__, alert)

    def process_repeat(self, alert: Alert, reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        return True, {}

    def process_action(self, alert: Alert, reason: Optional[str], action: str) -> Tuple[bool, Dict[str, Any]]:
        return super().process_action(alert, reason, action)

    def _process_alert(self, operation, alert):
        host, _ = self.get_contextual_configuration(VarDefinition('HOST', var_type=dict), alert, operation)
        trigger, _ = self.get_contextual_configuration(VarDefinition('TRIGGER', var_type=dict), alert, operation)
        host = host.get('HOST', alert.resource)
        trigger_name = trigger.get('NAME', alert.service)
        trigger_severity = trigger.get('SEVERITY', alert.severity)
        event_title, event_title_context = \
            self.get_contextual_configuration(VarDefinition('ALERTER_TITLE', var_type=str), alert, operation)
        alert_type, _ = self.get_contextual_configuration(VarDefinition('TYPE', var_type=str), alert, operation)
        if alert_type is None:
            alert_type = 'iometrics'

        alert_logos, _ = self.get_contextual_configuration(
            VarDefinition('alerter_logos', var_type=dict), alert, operation)

        if event_title_context and event_title_context == ConfigurationContext.AlerterConfig:
            if operation and operation == Alerter.process_recovery.__name__:
                event_title += ": Alert Recovery"
                trigger_severity = 'ok'
            else:
                event_title += ": New Alert Received"

        event_logo = alert_logos.get(alert_type, 'default').get(trigger_severity, 'unknown')

        event_time = alert.create_time.strftime('%d/%m/%Y, %H:%M:%S')
        max_length, _ = self.get_contextual_configuration(VarDefinition(
            'max_message_characters', var_type=int), alert, Alerter.process_event.__name__)
        message_sections = self.split_message(alert.text, max_length)

        chats_list, _ = self.get_contextual_configuration(VarDefinition('GCHAT'), alert,
                                                          Alerter.process_event.__name__)
        chats_list = self._get_gchat_chats(chats_list)
        response = None
        try:
            for idx, section in enumerate(message_sections):
                event_message = {
                    "text": event_title + ". " + host + ". " + trigger_name,
                    "previewText": event_title + ". " + host + ". " + trigger_name,
                    "fallbackText": event_title + ". " + host + ". " + trigger_name,
                    "cards": [
                        {
                            "header": {
                                "title": event_title,
                                "subtitle": "Triggered - " + event_time,
                                "imageUrl": event_logo,
                                "imageStyle": "IMAGE"
                            },
                            "sections": [
                                {
                                    "widgets": [
                                        {
                                            "keyValue": {
                                                "topLabel": "Message",
                                                "content": section
                                            }
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
                if chats_list:
                    for idy, chat_url in enumerate(chats_list):
                        response = self._send_message_to_gchat(chat_url, event_message)
                        if response and response.status_code in (200, 201):
                            logger.info("GChat %s notified successfully", str(chat_url))
                        else:
                            logger.warning("Could not notify GChat: %s", str(chat_url))
        except Exception as e:
            logger.exception("UNHANDLED EXCEPTION: %s", str(e))

        return response.status_code in (200, 201), {}

    def _get_gchat_chats(self, gchat_tag):
        chats_lists = set()
        if gchat_tag:
            if isinstance(gchat_tag, list):
                gchats = ''
                for chat in gchat_tag:
                    gchats = gchats.join(f'{chat},')
                gchat_tag = gchats
            chats = gchat_tag.replace(' ', '').split(',')
            for chat in chats:
                if re.search(GOOGLE_CHAT_URL_REGEX, chat):
                    chats_lists.add(chat)
                elif re.search('^id_(.*)', chat):
                    alias_url = self._config.get('chat_directory', {}).get(re.search('^id_(.*)', chat).group(1))
                    if not alias_url:
                        logger.warning("Invalid gchat %s. Set the entry in directory without prefix id_." % chat)
                    else:
                        chats_lists.add(alias_url)
                else:
                    logger.warning("Invalid gchat %s. Please use id_ prefix or direct url" % chat)
        else:
            logger.warning("No 'GCHAT' tag for gchat alerter")

        return chats_lists

    @staticmethod
    def _send_message_to_gchat(chat_url, message):
        response = None
        warn = True
        start = time.time()
        response_message = "SEND GCHAT MESSAGE"
        try:
            logger.info("REQUEST " + response_message,
                        extra={
                            'operation': Alerter.process_event.__name__,
                            'chat_url': chat_url,
                            'request_data': message
                        })
            response = requests.post(chat_url, json=message, proxies={})
        except Exception as e:
            logger.warning("ERROR sending information to Google Chat: {}".format(str(e)))
            response_message = "ERROR SENDING GCHAT MESSAGE"
        else:
            logger.debug("Message sent to Google Chat; chat: '{}', message: '{}'".format(chat_url, message))
            warn = False
        finally:
            logger_func = logger.warning if warn else logger.info
            logger_func("%s", response_message,
                        extra={
                            'operation': Alerter.process_event.__name__,
                            'chat_url': chat_url,
                            'status': response.status_code if response else -1,
                            'success': response.status_code in (200, 201) if response else False,
                            'duration': time.time() - start,
                            'response': response.json() if response else {}}
                        )
            return response

    @staticmethod
    def split_message(message, max_characters):
        message_pieces = []
        raw_message = message

        while len(raw_message) > max_characters:
            section_pieces = raw_message[:max_characters].rsplit('\n', 1)
            message_pieces.append(section_pieces[0])
            raw_message = raw_message[len(section_pieces[0]) + 1:]
        message_pieces.append(raw_message)

        return message_pieces

    @staticmethod
    def _get_url_zabbix_logo(priority):
        return {
            'indeterminate': 'https://i.imgur.com/uj44LrX.png',
            'informational': 'https://i.imgur.com/9dmJ570.png',
            'warning': 'https://i.imgur.com/8fRX14C.png',
            'minor': 'https://i.imgur.com/8RACcnC.png',
            'major': 'https://i.imgur.com/2HYYLSG.png',
            'critical': 'https://i.imgur.com/pIWU2Dv.png',
        }.get(priority, 'https://i.imgur.com/uj44LrX.png')


class GChatPlugin(IOMAlerterPlugin):

    def get_alerter_class(self):
        return GChatAlerter
