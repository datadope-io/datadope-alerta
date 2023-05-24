from datetime import timedelta

from datadope_alerta import CONFIG_AUTO_CLOSE_TASK_INTERVAL, \
    NormalizedDictView, DEFAULT_AUTO_CLOSE_TASK_INTERVAL, ContextualConfiguration, thread_local

from . import app, celery, db, getLogger, Alert, Status, AlertaClient

logger = getLogger(__name__)


@celery.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    config = NormalizedDictView(kwargs['source'])
    # Schedule auto close task
    interval = config.get(CONFIG_AUTO_CLOSE_TASK_INTERVAL, DEFAULT_AUTO_CLOSE_TASK_INTERVAL)
    sender.add_periodic_task(timedelta(seconds=interval),
                             check_automatic_closing.s(),
                             name='auto_close')
    from alerta.app import plugins
    for plugin in plugins.plugins.values():
        if getattr(plugin, 'register_periodic_tasks', None):
            with app.app_context():
                tasks = plugin.register_periodic_tasks(config)
            for task_class, schedule in tasks:
                if isinstance(schedule, (int, float)):
                    schedule = timedelta(seconds=schedule)
                sender.add_periodic_task(schedule, task_class.s())


class ClientTask(celery.Task):

    __alerta_client = None

    @property
    def alerta_client(self):
        if self.__alerta_client is None:
            alerta_client_config = ContextualConfiguration.get_global_configuration(
                ContextualConfiguration.ALERTACLIENT_CONFIGURATION, global_config=app.config)
            self.__alerta_client = AlertaClient(**alerta_client_config)
        return self.__alerta_client


@celery.task(base=ClientTask, bind=True, ignore_result=True, queue=app.config.get('AUTO_CLOSE_TASK_QUEUE'))
def check_automatic_closing(self):
    thread_local.alert_id = None
    thread_local.alerter_name = 'system'
    thread_local.operation = 'auto_close'

    logger.debug('Automatic closing task launched')
    try:
        to_close_ids = db.get_must_close_ids(limit=100)
        if to_close_ids:
            # noinspection PyPackageRequirements
            from flask import g
            g.login = 'system'
            action = 'close'
            text = 'Auto closed alert'
            for alert_id in to_close_ids:
                thread_local.alert_id = alert_id
                alert = Alert.find_by_id(alert_id)
                if alert:
                    if alert.status not in (Status.Closed, Status.Expired):
                        response = self.alerta_client.action(alert_id, action, text)
                        if response.get('status', '').lower() == 'ok':
                            logger.info("Alert close action requested successfully")
                        else:
                            logger.warning("Error received from alerta server closing alert: %s", response)
    except Exception as e:
        logger.warning("Error closing alerts: %s", e)
    finally:
        thread_local.alerter_name = None
        thread_local.operation = None
