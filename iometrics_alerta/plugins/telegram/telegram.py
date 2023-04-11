import os
from typing import Optional, Tuple, Dict, Any

import requests  # noqa
import yaml  # noqa

from alerta.models.alert import Alert
from iometrics_alerta import get_config, logger, VarDefinition
from iometrics_alerta.plugins.iom_plugin import Alerter, IOMAlerterPlugin

CONFIG = 'config.yml'
CONFIG_KEY = 'alerta_config_telegram'


class TelegramAlerter(Alerter):
    _config = None

    @classmethod
    def get_default_configuration(cls) -> dict:
        if cls._config is None:
            cls._config = cls.read_default_configuration()
        return cls._config

    @staticmethod
    def read_default_configuration():
        conf_file = get_config(key=CONFIG_KEY, default=os.path.join(os.path.dirname(__file__),
                                                                    CONFIG))
        with open(conf_file, 'r') as file:
            return yaml.safe_load(file.read())

    def process_repeat(self, alert: Alert, reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        return True, {}

    def process_action(self, alert: Alert, reason: Optional[str], action: str) -> Tuple[bool, Dict[str, Any]]:
        return super().process_action(alert, reason, action)

    def process_recovery(self, alert: Alert, reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        return self._process_alert(Alerter.process_recovery.__name__, alert)

    def process_event(self, alert: Alert, reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        return self._process_alert(Alerter.process_event.__name__, alert)

    def _process_alert(self, operation, alert: Alert):
        try:
            chats_list, _ = self.get_contextual_configuration(VarDefinition('TELEGRAM_CHATS', var_type=str),
                                                              alert,
                                                              operation=operation)
            if not chats_list:
                logger.error("TAG \"TELEGRAM_CHATS\" NOT EXISTS OR IS EMPTY!")
                return False, {}

            chats_list = chats_list.split(',')

            notification_sound, _ = self.get_contextual_configuration(VarDefinition('TELEGRAM_SOUND', var_type=int),
                                                                      alert,
                                                                      operation=operation)
            if not notification_sound:
                notification_sound = 1

            telegram_bot, _ = self.get_contextual_configuration(VarDefinition('BOTS', var_type=str),
                                                                alert,
                                                                operation=operation)
            if not telegram_bot:
                logger.error("TAG \"BOTS\" NOT EXISTS OR IS EMPTY!")
                return False, {}

            bot_token = None
            try:
                bot_token = self._config.get('bots').get(telegram_bot, {}).get('token', None)
            except KeyError:
                logger.error("CONFIG BOT \"%s\" AND OR TOKEN NOT EXISTS!")

            if not bot_token:
                logger.error("CONFIG BOT \"%s\" AND OR TOKEN NOT EXISTS!")
                return False, {}

            else:
                message_sections = self.split_message(alert.value,
                                                      self._config.get('max_message_characters', 4000))
                for chat_id in chats_list:
                    for message in message_sections:
                        self._send_telegram_message(message, bot_token, chat_id, notification_sound,
                                                    trigger_type="PROBLEM")

            return True, {}
        except Exception as e:
            logger.error("EXCEPTION UNHANDLED IN TELEGRAM PLUGIN! '%s'", str(e))

    def _send_telegram_message(self, message, bot_token, chat_id, notification_sound, trigger_type="PROBLEM"):
        response = None
        really_sent = False
        response_message = "SEND TELEGRAM MESSAGE"

        txt = self.get_txt(trigger_type, message)

        request_params = {
            "chat_id": str(chat_id),
            "disable_notification": int(notification_sound),
            "text": str(txt)
        }

        url = self._config.get('url') % bot_token

        if not really_sent:
            logger.info("REQUEST " + trigger_type)

            try:
                response = requests.get(url, params=request_params,
                                        timeout=int(self._config.get('message_send_timeout_s', 10)))
                response.raise_for_status()
            except requests.exceptions.RequestException:
                logger.warning("ERROR sending message to Telegram: %s" % str(response))

            else:
                warn = False
                logger.debug("Message sent to Telegram; chat: '{}', message: '{}'".format(chat_id, message))
                logger_func = logger.warning if warn else logger.info
                logger_func("%s", response_message)

                if response.json()["ok"]:
                    return response
                else:
                    logger.error("ERROR sending message to Telegram: %s" % str(response.json()))
                    return None

    @staticmethod
    def get_txt(trigger_type, message):
        if trigger_type == "PROBLEM":
            return str("\U0000274c \U0000274c \U0000274c \n" + message)
        elif trigger_type == "RECOVERY":
            return str("\U00002714 \U00002714 \U00002714 \n" + message)

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


class TelegramPlugin(IOMAlerterPlugin):
    def get_alerter_class(self):
        return TelegramAlerter
