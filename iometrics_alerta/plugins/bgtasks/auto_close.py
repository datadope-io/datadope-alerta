from datetime import timedelta

from iometrics_alerta import CONFIG_AUTO_CLOSE_TASK_INTERVAL, \
    ConfigKeyDict, DEFAULT_AUTO_CLOSE_TASK_INTERVAL

from . import app, celery, db, getLogger, Alert, Status, AlertaClient

logger = getLogger(__name__)


@celery.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    config = ConfigKeyDict(kwargs['source'])
    # Schedule auto close task
    interval = config.get(CONFIG_AUTO_CLOSE_TASK_INTERVAL, DEFAULT_AUTO_CLOSE_TASK_INTERVAL)
    sender.add_periodic_task(timedelta(seconds=interval),
                             check_automatic_closing.s(),
                             name='auto close')


class ClientTask(celery.Task):
    alerta_client_config = app.config.get('ALERTACLIENT_CONFIGURATION')
    alerta_client = AlertaClient(**alerta_client_config)


@celery.task(base=ClientTask, bind=True, ignore_result=True, queue=app.config.get('AUTO_CLOSE_TASK_QUEUE'))
def check_automatic_closing(self):
    logger.info('Automatic closing task launched')
    try:
        to_close_ids = db.get_must_close_ids(limit=100)
        if to_close_ids:
            # noinspection PyPackageRequirements
            from flask import g
            g.login = 'system'
            action = 'close'
            text = 'Auto closed alert'
            for alert_id in to_close_ids:
                alert = Alert.find_by_id(alert_id)
                if alert:
                    if alert.status not in (Status.Closed, Status.Expired):
                        response = self.alerta_client.action(alert_id, action, text)
                        if response.get('status', '').lower() == 'ok':
                            logger.info("Alert %s close action requested successfully", alert_id)
                        else:
                            logger.warning("Error received from alerta server closing alert %s: %s",
                                           alert_id, response)
    except Exception as e:
        logger.warning("Error closing alerts: %s", e)
