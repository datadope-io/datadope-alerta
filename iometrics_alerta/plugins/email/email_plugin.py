import json
import re
from typing import Any, Dict, Tuple, Optional

from alerta.models.alert import Alert
from iometrics_alerta.plugins import getLogger, VarDefinition
from iometrics_alerta.plugins.iom_plugin import Alerter, IOMAlerterPlugin

from .emailer import send_email, simple_email_address_validation
from ... import NormalizedDictView

CONFIG_KEY_SERVER = 'server'
CONFIG_KEY_SERVER_HOST = 'host'
CONFIG_KEY_SERVER_PORT = 'port'
CONFIG_KEY_SERVER_USER = 'user'
CONFIG_KEY_SERVER_PASSWORD = 'password'
CONFIG_KEY_SERVER_USE_TLS = 'tls_mode'
CONFIG_KEY_SERVER_KEY_FILE = 'tls_key_file'
CONFIG_KEY_SERVER_CERT_FILE = 'tls_cert_file'
CONFIG_KEY_SERVER_LOCAL_HOSTNAME = 'local_hostname'

CONFIG_DEFAULT_SERVER_PORT = 25

DATA_EMAIL_SENDER = 'sender'
DATA_EMAIL_SUBJECT = 'subject'
DATA_EMAIL_CONTENT_TYPE = 'contentType'

TAG_EMAILS_PREFIX = "EMAILS"
DATA_EMAIL_RECIPIENTS = 'recipients'
DATA_EMAIL_SENDTO = 'sendto'

TAG_EMAILFILE_PREFIX = "EMAILFILE"
DATA_EMAIL_FILES = "attachments"

TAG_EMAILS_NO_RECOVERY = "EMAILS_NO_RECOVERY"

RETURN_KEY_EMAILS = 'emails'

ERROR_REASON_NO_RECIPIENTS = 'no_recipients'
ERROR_REASON_IGNORE_RECOVERY = 'ignore_recovery'

logger = getLogger(__name__)


class EMailAlerter(Alerter):

    def __init__(self, name, bgtask=None):
        super().__init__(name, bgtask)
        for k, v in self.config.items():
            if NormalizedDictView.key_transform(k) in ('server', 'tasksdefinition') \
                    and isinstance(v, str):
                self.config[k] = json.loads(v)

    @staticmethod
    def _email_get_addresses_from_list(addresses) -> set:
        if not addresses:
            return set()
        if not isinstance(addresses, (list, set)):
            return {x.strip() for x in str(addresses).split(',')}
        else:
            return set(addresses)

    @staticmethod
    def _get_list_of_elements(tag_prefix, event_tags) -> set:
        elements = set()
        for tag, addresses in event_tags.items():
            if tag.startswith(tag_prefix):
                elements = elements | EMailAlerter._email_get_addresses_from_list(addresses)
        return elements

    @staticmethod
    def get_tag_by_type_or_global(event_type, event_tags, tag):
        key = event_type.upper() + '_' + tag
        if key in event_tags:
            return event_tags[key]
        else:
            return event_tags.get(tag) or ''

    def _process_request(self, operation, alert, reason: str) -> Tuple[bool, Dict[str, Any]]:  # noqa
        sender, _ = self.get_contextual_configuration(VarDefinition(DATA_EMAIL_SENDER, var_type=str),
                                                      alert,
                                                      operation=operation)
        subject, _ = self.get_contextual_configuration(VarDefinition(DATA_EMAIL_SUBJECT, var_type=str),
                                                       alert,
                                                       operation=operation)
        event_tags = self.get_event_tags(alert, operation)

        full_message = self.get_message(alert, operation, self.__class__.__name__)
        content_type, _ = self.get_contextual_configuration(VarDefinition(DATA_EMAIL_CONTENT_TYPE),
                                                            alert, operation)

        to = self._get_list_of_elements(TAG_EMAILS_PREFIX, event_tags) or set()
        for tag in (DATA_EMAIL_RECIPIENTS, DATA_EMAIL_SENDTO):
            to.update(self.get_contextual_configuration(VarDefinition(tag, default=[]),
                                                        alert, operation=operation)[0])
        to = list(filter(simple_email_address_validation, to))

        if operation == Alerter.process_event.__name__:
            files_old = self._get_list_of_elements(TAG_EMAILFILE_PREFIX, event_tags)
            files_new = set(self._email_get_addresses_from_list(self.get_contextual_configuration(
                VarDefinition(DATA_EMAIL_FILES, default=[]), alert, operation=operation)[0]))
            files = list(files_old | files_new)
        else:
            files = []

        if not to:
            logger.warning("NO ADDRESSES TO SEND EMAIL TO")
            return False, self.failure_response(reason=ERROR_REASON_NO_RECIPIENTS,
                                                message=f"No destination email addresses has been received")
        server_config = self.config[CONFIG_KEY_SERVER]
        host = server_config[CONFIG_KEY_SERVER_HOST]
        port = server_config.get(CONFIG_KEY_SERVER_PORT, CONFIG_DEFAULT_SERVER_PORT)
        user = server_config.get(CONFIG_KEY_SERVER_USER)
        password = server_config.get(CONFIG_KEY_SERVER_PASSWORD)
        tls_mode = server_config.get(CONFIG_KEY_SERVER_USE_TLS)
        key_file = server_config.get(CONFIG_KEY_SERVER_KEY_FILE)
        cert_file = server_config.get(CONFIG_KEY_SERVER_CERT_FILE)
        local_hostname = server_config.get(CONFIG_KEY_SERVER_LOCAL_HOSTNAME)
        body = full_message
        if not subject:
            logger.warning("Tag %s not found. Getting subject from message", DATA_EMAIL_SUBJECT)
            regex = r"<title>(.*)<\/title>"
            match = re.findall(regex, full_message, re.MULTILINE | re.IGNORECASE)
            if match:
                subject = match[0]
            else:
                subject = full_message.strip().split('\n')[0]
        logger.info("SENDING EMAIL USING SERVER `%s:%d' WITH SUBJECT: '%s' TO %d EMAIL ADDRESSES",
                    host, port, subject, len(to))
        if not content_type:
            if '<!doctype html>' in full_message.lower() \
                    or '</html>' in full_message.lower() \
                    or '</body>' in full_message.lower():
                content_type = 'text/html'
            else:
                content_type = 'text/plain'
        dry_run = self.is_dry_run(alert, operation)
        if dry_run:
            logger.debug("BODY: %s", body)
            return True, {RETURN_KEY_EMAILS: "0/0", "DRY-RUN": True}
        response = send_email(smtp_server=host, smtp_port=port,
                              smtp_login_user=user, smtp_login_password=password,
                              from_=sender, to=to, subject=subject, body=body, body_content_type=content_type,
                              files=files, tls_mode=tls_mode, cert_file=cert_file, key_file=key_file,
                              local_hostname=local_hostname)
        if response:
            logger.warning("EMAILS SENT PARTIALLY: %d OF %d EMAIL ADDRESSES WERE WRONG", len(response), len(to))
            sent = len(to) - len(response)
        else:
            logger.info("EMAILS SENT SUCCESSFULLY TO %d EMAIL ADDRESSES", len(to))
            sent = len(to)
        return True, {RETURN_KEY_EMAILS: f"{sent}/{len(to)}"}

    @classmethod
    def get_default_configuration(cls) -> dict:
        return {
            "server": {
                "host": "smtpserver",
                "port": 25,
                "user": None,
                "password": None,
                "tls_mode": None,  # Can be starttls or ssl
                "tls_key_file": None,
                "tls_cert_file": None,
                "local_hostname": "myhostname.domain.org"
            },
            "sender": "alerta@datadope.io",
            "subject": {
                "new": "NEW PROBLEM in {{ alert.resource }}: {{ alert.event }} {{ alert.text }}",
                "recovery": "RECOVERY FOR PROBLEM {{ alert.event }} in {{ alert.resource }}",
                "repeat": "REPEATING PROBLEM in {{ alert.resource }}: {{ alert.event }} {{ alert.text }}"
            }
        }

    def process_event(self, alert: Alert, reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        return self._process_request(Alerter.process_event.__name__, alert, reason)

    def process_recovery(self, alert: Alert, reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        event_tags = self.get_event_tags(alert, operation='recovery')
        if TAG_EMAILS_NO_RECOVERY in event_tags:
            logger.info("IGNORING RECOVERY ACTION. SHOULD USE 'IGNORE_RECOVERY' INSTEAD OF %s. Exiting",
                        TAG_EMAILS_NO_RECOVERY)
            return False, self.failure_response(reason=ERROR_REASON_IGNORE_RECOVERY,
                                                message=f"Received event tag {TAG_EMAILS_NO_RECOVERY}")
        return self._process_request(Alerter.process_recovery.__name__, alert, reason)

    def process_repeat(self, alert: 'Alert', reason: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
        return True, {}

    def process_action(self, alert: 'Alert', reason: Optional[str], action: str) -> Tuple[bool, Dict[str, Any]]:
        return super().process_action(alert, reason, action)


class EMailPlugin(IOMAlerterPlugin):

    def get_alerter_class(self):
        return EMailAlerter
