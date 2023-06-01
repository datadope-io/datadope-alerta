import logging
import mimetypes
import os
import re
import ssl

from smtplib import SMTP, SMTPNotSupportedError, SMTP_SSL

HTML_CONTENT_TYPE_GUESS_REGEX = r"<!DOCTYPE +html>"

_html_pattern = re.compile(HTML_CONTENT_TYPE_GUESS_REGEX, re.MULTILINE | re.IGNORECASE)


def guess_is_html(body):
    return _html_pattern.match(body)


# noinspection PyBroadException
try:
    # noinspection PyUnresolvedReferences
    from email.message import EmailMessage
    old_python = False
except Exception:
    from email import encoders
    from email.mime.audio import MIMEAudio
    from email.mime.base import MIMEBase
    from email.mime.image import MIMEImage
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.utils import formatdate
    old_python = True

logger = logging.getLogger(__name__)


def simple_email_address_validation(address: str):
    if address:
        name, _, domain = address.partition('@')
        if name and domain:
            components = domain.split('.')
            if len(components) > 1 and len(components[-1]) >= 2 and not name.startswith('.') and '..' not in domain:
                return True
    logger.warning("Wrong email address: %s", address)
    return False


def _send_email(server_host, server_port, from_, to, message, username=None, password=None,
                tls_mode=None, key_file=None, cert_file=None, local_hostname=None):
    smtp = None
    ctx = None
    if tls_mode is not None:
        ctx = ssl.create_default_context()
        if key_file is not None or cert_file is not None:
            ctx.load_cert_chain(certfile=cert_file, keyfile=key_file)
        else:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
    try:
        if tls_mode and tls_mode.lower() == 'ssl':
            smtp = SMTP_SSL(host=server_host, port=server_port, local_hostname=local_hostname, context=ctx)
        else:
            smtp = SMTP(host=server_host, port=server_port, local_hostname=local_hostname)
            if tls_mode and tls_mode.lower() == 'starttls':
                try:
                    smtp.starttls(context=ctx)
                except SMTPNotSupportedError as e:
                    logger.warning('%s. Trying with a plain connection', e)
        if username and password:
            smtp.login(user=username, password=password)
        if old_python:
            response = smtp.sendmail(from_addr=from_, to_addrs=to, msg=message)
        else:
            # noinspection PyUnresolvedReferences
            response = smtp.send_message(message)
        return response
    except Exception as e:
        logger.warning("Error sending email message: %s", e)
        raise
    finally:
        if smtp is not None:
            smtp.quit()


def _prepare_message(from_, to, subject="", body="", files=None, body_subtype="plain"):
    if files is None:
        files = []
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = from_
    msg['To'] = ', '.join(to)
    if body:
        msg.set_content(body, body_subtype)
    for path in files:
        try:
            filename = os.path.basename(path)
            # Guess the content type based on the file's extension.
            ctype, encoding = mimetypes.guess_type(path)
            if ctype is None or encoding is not None:
                ctype = 'application/octet-stream'
            maintype, subtype = ctype.split('/', 1)
            with open(path, 'rb') as fp:
                msg.add_attachment(fp.read(),
                                   maintype=maintype,
                                   subtype=subtype,
                                   filename=filename)
        except Exception as e:
            logger.warning("Not attaching file %s: %s", path, e)
    return msg


def _prepare_message_old(from_, to, subject="", body="", files=None, body_subtype="plain"):
    outer = MIMEMultipart()
    outer['From'] = from_
    outer['To'] = ', '.join(to)
    outer['Date'] = formatdate(localtime=True)
    outer['Subject'] = subject

    if type(body).__name__ == 'unicode':
        body = body.encode("utf-8")

    outer.attach(MIMEText(body, body_subtype, _charset="utf_8"))

    for path in files or []:
        try:
            filename = os.path.basename(path)
            # Guess the content type based on the file's extension.  Encoding
            # will be ignored, although we should check for simple things like
            # gzip'd or compressed files.
            ctype, encoding = mimetypes.guess_type(path)
            if ctype is None or encoding is not None:
                # No guess could be made, or the file is encoded (compressed), so
                # use a generic bag-of-bits type.
                ctype = 'application/octet-stream'
            maintype, subtype = ctype.split('/', 1)
            if maintype == 'text':
                fp = open(path)
                # Note: we should handle calculating the charset
                msg = MIMEText(fp.read(), _subtype=subtype)
                fp.close()
            elif maintype == 'image':
                fp = open(path, 'rb')
                msg = MIMEImage(fp.read(), _subtype=subtype)
                fp.close()
            elif maintype == 'audio':
                fp = open(path, 'rb')
                msg = MIMEAudio(fp.read(), _subtype=subtype)
                fp.close()
            else:
                fp = open(path, 'rb')
                msg = MIMEBase(maintype, subtype)
                msg.set_payload(fp.read())
                fp.close()
                # Encode the payload using Base64
                encoders.encode_base64(msg)
            # Set the filename parameter
            msg.add_header('Content-Disposition', 'attachment', filename=filename)
            outer.attach(msg)
        except Exception as e:
            logger.warning("Not attaching file %s: %s", path, e)
    return outer.as_string()


def send_email(from_, to, smtp_server, subject="", body="", body_content_type=None, files=None,
               smtp_port=25, smtp_login_user=None, smtp_login_password=None,
               tls_mode=None, key_file=None, cert_file=None, local_hostname=None):
    """
    Send email to a list of recipients. This method raises an exception if all recipients refused the email.

    :param str smtp_server: SMTP server to connect to send the email
    :param int smtp_port: port listening to SMTP protocol in smtp server
    :param str from_: From address to use to send the email
    :param list to: List of recipients' addresses
    :param str subject: Subject of the email
    :param str body: Body of the email
    :param str body_content_type: Content type of the body. Usually text/plain or text/html. If None, it tries to guess
    if it is html if <!DOCTYPE html> is present in the body.
    :param list files: File paths to files to send as attachments
    :param str smtp_login_user: username to connect to the SMTP server if needed
    :param str smtp_login_password: password to connect to the SMTP server if needed
    :param str tls_mode: 'starttls' or 'ssl' to connect in a secure way
    :param str key_file: specific key file to check connection
    :param str cert_file: specific cert file to check connection
    :param str local_hostname: origin hostname to send to the smtp server
    :return: If this method does not raise an exception, it returns a dictionary,
      with one entry for each recipient that was refused.
      Each entry contains a tuple of the SMTP error code and the accompanying error message sent by the server.
    :rtype: dict
    """
    if smtp_port is None:
        smtp_port = 25

    if body_content_type is None:
        body_content_type = 'text/html' if guess_is_html(body) else 'text/plain'
    subtype = body_content_type.split('/')[-1].split(';')[0].strip().lower()

    if old_python:
        message = _prepare_message_old(from_=from_,
                                       to=to,
                                       subject=subject,
                                       body=body,
                                       files=files,
                                       body_subtype=subtype)
    else:
        message = _prepare_message(from_=from_,
                                   to=to,
                                   subject=subject,
                                   body=body,
                                   files=files,
                                   body_subtype=subtype)

    return _send_email(from_=from_, to=to, message=message,
                       server_host=smtp_server, server_port=smtp_port,
                       username=smtp_login_user, password=smtp_login_password,
                       tls_mode=tls_mode, cert_file=cert_file, key_file=key_file, local_hostname=local_hostname)
