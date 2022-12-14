from typing import Any, Dict, Tuple, Optional

# noinspection PyPackageRequirements
from jinja2 import TemplateNotFound

from alerta.models.alert import Alert
from iometrics_alerta.plugins import getLogger, VarDefinition
from iometrics_alerta.plugins.iom_plugin import Alerter, IOMAlerterPlugin

from .emailer import send_email, simple_email_address_validation

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
DATA_EMAIL_TEMPLATE = 'template'
DATA_EMAIL_CONTENT_TYPE = 'contentType'
DATA_EMAIL_MESSAGE = 'message'

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

    def _process_request(self, operation, alert, reason) -> Tuple[bool, Dict[str, Any]]:
        sender, _ = self.get_contextual_configuration(VarDefinition(DATA_EMAIL_SENDER, var_type=str),
                                                      alert,
                                                      operation=operation)
        subject, _ = self.get_contextual_configuration(VarDefinition(DATA_EMAIL_SUBJECT, var_type=str),
                                                       alert,
                                                       operation=operation)
        event_tags = self.get_event_tags(alert, operation)

        full_message = None
        template, _ = self.get_contextual_configuration(VarDefinition(DATA_EMAIL_TEMPLATE), alert, operation)
        if template:
            try:
                full_message = self.render_template(template, alert=alert, operation=operation)
            except TemplateNotFound:
                logger.warning("Template %s not found for email Alerter. Using other options to create message",
                               template)
            except Exception as e:
                logger.warning("Error rendering template: %s. Using other options to create message", e, exc_info=e)
        if not full_message:
            full_message, _ = self.get_contextual_configuration(
                VarDefinition(DATA_EMAIL_MESSAGE, default=''), alert, operation=operation)
            if not full_message:
                if operation == Alerter.process_recovery.__name__:
                    full_message = reason
                    if not full_message:
                        full_message = alert.text
                else:
                    text = alert.text or ''
                    full_message = text.strip()
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
        if subject:
            body = full_message
        else:
            logger.warning("Tag %s not found. Using first message line as subject", DATA_EMAIL_SUBJECT)
            subject, _, body = full_message.strip().partition('\n')
        if not body:
            body = subject
        logger.info("SENDING EMAIL USING SERVER `%s:%d' WITH SUBJECT: '%s'", host, port, subject)
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


class EMailPlugin(IOMAlerterPlugin):

    def get_alerter_class(self):
        return EMailAlerter

    def get_alerter_default_configuration(self) -> dict:
        return {
            # "action_delay": 30,  # Use default
            # "tasks_definition": {
            #     "new": {
            #         "queue": "email",
            #         "priority": 5
            #     },
            #     "recovery": {
            #         "queue": "email_recovery",
            #         "priority": 6
            #     }
            # },
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
                "new": "NEW PROBLEM in {{ alert.resource }}",
                "recovery": "RECOVERY: problem in {{ alert.resource }} is been resolved"
            },
            "template": {
                "new": "email/new_event.html",
                "recovery": "email/recovery.html"
            },
            "content_type": "text/html"
        }
