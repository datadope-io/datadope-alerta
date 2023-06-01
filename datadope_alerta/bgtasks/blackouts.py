from datetime import datetime

import flask
from flask import g, current_app
from werkzeug.datastructures import MultiDict
from alerta.app import qb
from alerta.utils.api import process_alert

from . import celery, getLogger, Alert
from .. import ContextualConfiguration, thread_local
from ..plugins.blackouts import BLACKOUT_TASK_QUEUE
from ..plugins.blackouts.plugin import BlackoutManager

logger = getLogger(__name__)


def get_queue():
    return ContextualConfiguration.get_global_configuration(BLACKOUT_TASK_QUEUE)

@celery.task(base=celery.Task, ignore_result=True, queue=get_queue())
def check_still_in_blackout():
    thread_local.alert_id = None
    thread_local.alerter_name = 'blackout_manager'
    thread_local.operation = 'check_still_in_blackout'
    try:
        query = qb.alerts.from_params(MultiDict([('status', str('blackout'))]))
        alerts_in_blackout = Alert.find_all(query)
    except Exception as e:
        logger.warning("Exception getting alerts with status = blackout: %s", e)
    else:
        if alerts_in_blackout:
            logger.info("Alerts in blackout: %s", ", ".join([x.id for x in alerts_in_blackout]))
            for alert in alerts_in_blackout:
                if not check_alert_still_in_blackout(alert):
                    logger.info("Alert '%s' not in blackout anymore. Changing status to open", alert.id)
                    open_alert(alert)
        else:
            logger.debug("No alert in blackout status")
    thread_local.alerter_name = None
    thread_local.operation = None

def is_alert_in_blackout(alert, config):
    # If alert has to be rejected but severity in BLACKOUT_ACCEPT, create alert ignoring blckout
    if not config['NOTIFICATION_BLACKOUT'] and alert.severity in config['BLACKOUT_ACCEPT']:
        return False

    providers = BlackoutManager.get_providers(alert, config)
    for name, provider in providers.items():
        try:
            if provider.is_alert_in_blackout(alert, config):
                logger.debug("Alert marked in blackout by provider '%s'", name)
                return True
        except Exception as e:
            logger.warning("Unhandled exception raised by blackout provider '%s': %s", name, str(e))
    return False

def check_alert_still_in_blackout(alert):
    original = alert.create_time
    alert.create_time = datetime.utcnow()
    try:
        return is_alert_in_blackout(alert, flask.current_app.config)
    finally:
        alert.create_time = original

def open_alert(alert):
    try:
        g.login = 'system'
        alert.status = 'open'
        alert.create_time = datetime.utcnow()
        fake_environ = {'REMOTE_ADDR': '127.0.0.1'}
        with current_app.test_request_context(environ_base=fake_environ):
            process_alert(alert)
    except Exception as e:
        logger.error("Error opening alert '%s' after blackout: %s", alert.id, str(e))
        return