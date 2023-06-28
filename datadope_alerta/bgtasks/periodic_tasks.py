from datetime import timedelta

from datadope_alerta import CONFIG_AUTO_CLOSE_TASK_INTERVAL, \
    NormalizedDictView, DEFAULT_AUTO_CLOSE_TASK_INTERVAL, ContextualConfiguration, thread_local,  \
    CONFIG_AUTO_RESOLVE_TASK_INTERVAL, DEFAULT_AUTO_RESOLVE_TASK_INTERVAL

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
    # Schedule auto resolve task
    interval = config.get(CONFIG_AUTO_RESOLVE_TASK_INTERVAL, DEFAULT_AUTO_RESOLVE_TASK_INTERVAL)
    sender.add_periodic_task(timedelta(seconds=interval),
                             check_automatic_resolving.s(),
                             name='auto_resolve')
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
        to_close_ids = db.get_must_close_ids(limit=1000)
        if to_close_ids:
            action = 'close'
            text = 'Auto closed alert'
            _action_on_alerts(to_close_ids, action, text)
    except Exception as e:
        thread_local.alerter_name = 'system'
        thread_local.operation = 'auto_close'
        logger.warning("Error closing alerts: %s", e)
    finally:
        thread_local.alerter_name = None
        thread_local.operation = None

@celery.task(base=ClientTask, bind=True, ignore_result=True, queue=app.config.get('AUTO_RESOLVE_TASK_QUEUE'))
def check_automatic_resolving(self):
    thread_local.alert_id = None
    thread_local.alerter_name = 'system'
    thread_local.operation = 'auto_resolve'
    logger.debug('Automatic resolving task launched')
    try:
        to_resolve_ids = db.get_must_resolve_ids(limit=1000)
        if to_resolve_ids:
            action = 'resolve'
            text = 'Auto resolve alert'
            _action_on_alerts(to_resolve_ids, action, text)
    except Exception as e:
        thread_local.alerter_name = 'system'
        thread_local.operation = 'auto_resolve'
        logger.warning("Error resolving alerts: %s", e)
    finally:
        thread_local.alerter_name = None
        thread_local.operation = None

def _action_on_alerts(alerts_ids, action, text):
    from flask import current_app, g
    from alerta.utils.api import process_action
    g.login = 'system'
    for alert_id in alerts_ids:
        thread_local.alert_id = alert_id
        alert = Alert.find_by_id(alert_id)
        if alert:
            if alert.status not in (Status.Closed, Status.Expired):
                request_environ = {'REMOTE_ADDR': alert.attributes.get('ip', '127.0.0.1')}
                try:
                    with current_app.test_request_context(environ_base=request_environ):
                        alert, action, text, timeout = process_action(alert, action, text)
                        alert.from_action(action, text, timeout)
                        thread_local.alerter_name = 'system'
                        thread_local.operation = 'auto_' + action
                        logger.info("Alert '%s' action requested successfully", action)
                except Exception as e:
                    thread_local.alerter_name = 'system'
                    thread_local.operation = 'auto_' + action
                    logger.warning("Error auto '%s' alert: %s", action, e)
