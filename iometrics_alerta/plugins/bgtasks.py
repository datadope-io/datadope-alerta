import random
from datetime import datetime, timedelta
from typing import Optional

from requests.exceptions import ConnectionError as RequestsConnectionError, Timeout as RequestsTimeout

from alertaclient.api import Client

from alerta.app import create_app, create_celery_app, db
from alerta.models.alert import Alert
from alerta.models.enums import Status
from alerta.utils.collections import merge

# noinspection PyPackageRequirements
from celery import states, signature
# noinspection PyPackageRequirements
from celery.exceptions import Ignore
# noinspection PyPackageRequirements
from celery.utils.time import get_exponential_backoff_interval

from iometrics_alerta import DateTime, init_configuration, init_jinja_loader, CONFIG_AUTO_CLOSE_TASK_INTERVAL, \
    ConfigKeyDict, DEFAULT_AUTO_CLOSE_TASK_INTERVAL
from iometrics_alerta import AlerterProcessAttributeConstant as AProcC
from iometrics_alerta import BGTaskAlerterDataConstants as BGTadC
from iometrics_alerta.plugins import Alerter, getLogger, RetryableException, AlerterStatus

app = create_app()
celery = create_celery_app(app)

logger = getLogger(__name__)

init_configuration(app.config)
init_jinja_loader(app)


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
    alerta_client = Client(**alerta_client_config)


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


class EventTask(celery.Task):
    ignore_result = True
    _time_management = {}
    plugin_type = None

    @staticmethod
    def _get_attribute_name(alerter_name):
        return AProcC.ATTRIBUTE_FORMATTER.format(alerter_name=alerter_name)

    @classmethod
    def _get_parameters(cls, task_id, kwargs):  # task_id null for intermediate requests => begin time is not popped
        alerter_data = kwargs['alerter_data']
        alert = kwargs['alert']
        operation = kwargs['operation']
        alerter_name = alerter_data[BGTadC.NAME]
        alert_id = alert['id']
        now = datetime.now()
        duration = 0.0
        begin = None
        if task_id:
            begin = cls._time_management.pop(task_id, None)
            if begin:
                duration = (now - begin).total_seconds()
        return alert_id, operation, alerter_name, begin, now, duration

    @classmethod
    def _on_finish(cls, alerter_name, operation, alert_id, retval, start_time, end_time, duration,
                   alert_obj=None, update_db=True):
        attribute_name = cls._get_attribute_name(alerter_name)
        if start_time is None:
            if alert_obj is None:
                with app.app_context():
                    alert_obj = Alert.find_by_id(alert_id)
            key = AProcC.KEY_NEW_EVENT if operation == Alerter.process_event.__name__ \
                else AProcC.KEY_RECOVERY
            start_time = alert_obj.attributes.get(attribute_name, {})\
                .get(key, {}).get(AProcC.FIELD_START)
            if start_time:
                try:
                    start_time = DateTime.parse_utc(start_time)
                except ValueError:
                    start_time = None
        if (duration is None or duration == 0.0) and start_time is not None and end_time is not None:
            duration = DateTime.diff_seconds_utc(end_time, start_time)
        if cls.plugin_type is None:
            from iometrics_alerta.plugins.iom_plugin import IOMAlerterPlugin
            cls.plugin_type = IOMAlerterPlugin
        success, attribute_data = cls.plugin_type.prepare_result(operation=operation, retval=retval,
                                                                 start_time=start_time,
                                                                 end_time=end_time, duration=duration)
        logger.info("PROCESS FINISHED IN %.3f sec. RESULT %s FOR ALERT '%s' IN %s:%s -> %s",
                    duration,
                    'SUCCESS' if success else 'FAILURE',
                    alert_id, alerter_name, operation, retval)
        if alert_obj is None:
            with app.app_context():
                alert_obj = Alert.find_by_id(alert_id)
        data = alert_obj.attributes.setdefault(attribute_name, {})
        merge(data, attribute_data)
        if update_db:
            with app.app_context():
                alert_obj.update_attributes({attribute_name: data})

    def _ignore_recovery_while_processing(self, message, alert_obj, task_id, kwargs, event_retval):
        alert_id, _, alerter_name, start_time, end_time, duration = self._get_parameters(task_id, kwargs)
        attribute_name = self._get_attribute_name(alerter_name)
        alerter_attr_data = alert_obj.attributes.setdefault(attribute_name, {})
        recovery_retval = True, {"info": {"message": message}}
        EventTask._on_finish(alerter_name=alerter_name, operation=Alerter.process_event.__name__, alert_id=alert_id,
                             retval=event_retval, start_time=start_time, end_time=end_time, duration=duration,
                             alert_obj=alert_obj, update_db=False)
        _, attribute_data = self.plugin_type.prepare_result(operation=Alerter.process_recovery.__name__,
                                                            retval=recovery_retval,
                                                            start_time=None,
                                                            end_time=None,
                                                            duration=None,
                                                            new_status=AlerterStatus.Recovered)
        merge(alerter_attr_data, attribute_data)
        alerter_attr_data.pop(AProcC.FIELD_TEMP_RECOVERY_DATA, None)
        alert_obj.update_attributes({attribute_name: alerter_attr_data})
        self.update_state(state=states.IGNORED)

    def before_start(self, task_id, args, kwargs):  # noqa
        start_time = datetime.now()
        alert_id, operation, alerter_name, _, _, _ = self._get_parameters(None, kwargs)
        is_retrying = self.request.retries > 0
        if is_retrying:
            logger.info("Retry %d for task '%s:%s'. Alert: '%s'", self.request.retries,
                        alerter_name, operation, alert_id)
        else:
            self._time_management[task_id] = start_time
            logger.info("Starting task for '%s:%s'. Alert: '%s'", alerter_name, operation, alert_id)
        attribute_name = self._get_attribute_name(alerter_name)
        if operation == Alerter.process_event.__name__:
            new_status = AlerterStatus.Processing
            data_field = AProcC.KEY_NEW_EVENT
        else:
            new_status = AlerterStatus.Recovering
            data_field = AProcC.KEY_RECOVERY
        with app.app_context():
            alert_obj = Alert.find_by_id(alert_id)
            attr_data = alert_obj.attributes.setdefault(attribute_name, {})
            current_status = AlerterStatus(attr_data.get(AProcC.FIELD_STATUS))
            if new_status == AlerterStatus.Processing and current_status == AlerterStatus.Recovering:
                logger.info("Ignoring task %s:%s' for alert '%s' -> Alert recovered before alerting",
                            alerter_name, operation, alert_id)
                event_retval = not is_retrying, {"info": {"message": "RECOVERED BEFORE ALERTING"}}
                self._ignore_recovery_while_processing(message="RECOVERED BEFORE ALERTING OR RETRY.",
                                                       alert_obj=alert_obj, task_id=task_id, kwargs=kwargs,
                                                       event_retval=event_retval)
                self.update_state(state=states.IGNORED)
                raise Ignore()
            if (new_status == AlerterStatus.Processing and new_status == current_status and not is_retrying) \
                or (new_status == AlerterStatus.Processing and current_status not in (
                    AlerterStatus.New, AlerterStatus.Scheduled, AlerterStatus.Processing)):
                logger.warning("Ignoring task %s:%s' for alert '%s' -> Current status is not valid for this task: %s",
                               alerter_name, operation, alert_id, current_status.value)
                if EventTask.plugin_type is None:
                    from iometrics_alerta.plugins.iom_plugin import IOMAlerterPlugin
                    EventTask.plugin_type = IOMAlerterPlugin
                success, attribute_data = EventTask.plugin_type.prepare_result(
                    operation=operation, retval=(True, {"info": {"message": "RECOVERED BEFORE ALERTING"}}),
                    start_time=start_time, end_time=start_time, duration=0.0)
                attribute_data[AProcC.FIELD_STATUS] = current_status.value
                merge(attr_data, attribute_data)
                alert_obj.update_attributes({attribute_name: attr_data})
                self.update_state(state=states.IGNORED)
                raise Ignore()
            if not is_retrying:
                attr_data[AProcC.FIELD_STATUS] = new_status.value
                attr_data.setdefault(data_field, {})[AProcC.FIELD_START] = DateTime.iso8601_utc(start_time)
                alert_obj.update_attributes({attribute_name: attr_data})

    def on_success(self, retval, task_id, args, kwargs):  # noqa
        alert_id, operation, alerter_name, start_time, end_time, duration = self._get_parameters(task_id, kwargs)
        if operation == Alerter.process_event.__name__:
            attribute_name = self._get_attribute_name(alerter_name)
            with app.app_context():
                alert_obj = Alert.find_by_id(alert_id)
                attr_data = alert_obj.attributes
                alerter_attr_data = attr_data.setdefault(attribute_name, {})
                current_status = AlerterStatus(alerter_attr_data[AProcC.FIELD_STATUS])
                if current_status == AlerterStatus.Recovering:
                    # Recovered while processing, but processing was fine
                    if self.plugin_type is None:
                        from iometrics_alerta.plugins.iom_plugin import IOMAlerterPlugin
                        self.plugin_type = IOMAlerterPlugin
                    success, attribute_data = self.plugin_type.prepare_result(operation=operation, retval=retval,
                                                                              start_time=start_time,
                                                                              end_time=end_time, duration=duration)
                    logger.info("PROCESS FINISHED IN %.3f sec. RESULT %s FOR ALERT '%s' IN %s:%s -> %s",
                                duration,
                                'SUCCESS' if success else 'FAILURE',
                                alert_id, alerter_name, operation, retval)
                    merge(alerter_attr_data, attribute_data)
                    task_data = alerter_attr_data.pop(AProcC.FIELD_TEMP_RECOVERY_DATA, {})
                    reason = task_data.get(AProcC.FIELD_TEMP_RECOVERY_DATA_TEXT, alert_obj.text)
                    task_def = task_data.get(AProcC.FIELD_TEMP_RECOVERY_DATA_TASK_DEF, {})
                    alert_obj.update_attributes({attribute_name: alerter_attr_data})
                    kwargs['alert'] = alert_obj
                    kwargs['operation'] = Alerter.process_recovery.__name__
                    kwargs['reason'] = reason
                    logger.info("Alert %s recovered during processing. Sending recovery from processing task",
                                alert_id)
                    signature(run_in_bg, args=args, kwargs=kwargs).apply_async(countdown=5.0, **task_def)
                    return
        self._on_finish(alerter_name=alerter_name, operation=operation, alert_id=alert_id,
                        retval=retval, start_time=start_time, end_time=end_time, duration=duration)
    def on_failure(self, exc, task_id, args, kwargs, einfo):  # noqa
        alert_obj = None
        if self.plugin_type is None:
            from iometrics_alerta.plugins.iom_plugin import IOMAlerterPlugin
            self.plugin_type = IOMAlerterPlugin
        alert_id, operation, alerter_name, start_time, end_time, duration = self._get_parameters(task_id, kwargs)
        retval = False, self.plugin_type.result_for_exception(exc, einfo)
        if operation == Alerter.process_event.__name__:
            attribute_name = self._get_attribute_name(alerter_name)
            with app.app_context():
                alert_obj = Alert.find_by_id(alert_id)
                attr_data = alert_obj.attributes
                # Read status before updating it
                current_status = AlerterStatus(attr_data.setdefault(attribute_name, {})[AProcC.FIELD_STATUS])
                if current_status == AlerterStatus.Recovering:
                    # Recovered while processing. Ignoring recovery
                    logger.info("Alert %s recovered and processing failed. Ignoring recovery", alert_id)
                    self._time_management[task_id] = start_time
                    self._ignore_recovery_while_processing(message="RECOVERED BEFORE ALERTING. ALERTING FAILED",
                                                           alert_obj=alert_obj, task_id=task_id, kwargs=kwargs,
                                                           event_retval=retval)
                    return
        EventTask._on_finish(alerter_name=alerter_name, operation=operation, alert_id=alert_id, retval=retval,
                             start_time=start_time, end_time=end_time, duration=duration,
                             alert_obj=alert_obj, update_db=True)

    def on_retry(self, exc, task_id, args, kwargs, einfo):  # noqa
        if self.plugin_type is None:
            from iometrics_alerta.plugins.iom_plugin import IOMAlerterPlugin
            self.plugin_type = IOMAlerterPlugin
        alert_id, operation, alerter_name, _, _,  _ = self._get_parameters(None, kwargs)
        if operation == Alerter.process_event.__name__:
            attribute_name = self._get_attribute_name(alerter_name)
            with app.app_context():
                alert_obj = Alert.find_by_id(alert_id)
                attr_data = alert_obj.attributes
                current_status = AlerterStatus(attr_data.setdefault(attribute_name, {})[AProcC.FIELD_STATUS])
                if current_status == AlerterStatus.Recovering:
                    event_retval = False, self.plugin_type.result_for_exception(exc, einfo)
                    # Recovered while processing. Cancel retries and ignoring recovery
                    logger.info("Alert %s recovered before launching a processing retry. Cancelling retry and recovery",
                                alert_id)
                    revoke_task(task_id)
                    self._ignore_recovery_while_processing(message="RECOVERED BEFORE ALERTING DURING RETRY",
                                                           alert_obj=alert_obj, task_id=task_id, kwargs=kwargs,
                                                           event_retval=event_retval)
                    return
        countdown = self.request.properties.get('retry_spec', {}).get('_countdown_', 0.0)
        logger.info("SCHEDULED RETRY %d/%d IN %.0f secs. FOR ALERT '%s' IN %s:%s -> %s",
                    self.request.retries + 1, self.override_max_retries,
                    countdown,
                    alert_id, alerter_name, operation, exc)


def revoke_task(task_id):
    celery.control.revoke(task_id)


def get_retry_parameters(retry_number, retry_data):
    max_retries = retry_data['max_retries']
    interval_first = retry_data.get('interval_first', 2.0)
    interval_step = retry_data.get('interval_step', 0.2)
    interval_max = retry_data.get('interval_max', 0.2)
    jitter = retry_data.get('retry_jitter', False)

    if retry_data.get('exponential', False):
        countdown = get_exponential_backoff_interval(
            factor=interval_first,
            retries=retry_number,
            maximum=interval_max,
            full_jitter=jitter)
    else:
        countdown = min(interval_max, interval_first + retry_number * interval_step)
        if jitter:
            countdown = random.randrange(countdown + 1)
        countdown = max(0, countdown)

    return max_retries, countdown


@celery.task(base=EventTask, bind=True, ignore_result=True)
def run_in_bg(self, alerter_data: dict, alert: dict, operation: str, reason: Optional[str]):  # noqa
    alerter_name = alerter_data[BGTadC.NAME]
    alerter_class = alerter_data[BGTadC.CLASS]
    alerter_config = alerter_data[BGTadC.CONFIG]
    logger.debug("Running background task '%s:%s'", alerter_class, operation)
    alerter = Alerter.get_alerter_type(alerter_class)(alerter_name, alerter_config)
    try:
        response = getattr(alerter, operation)(Alert.parse(alert), reason)
        return response
    except (RetryableException, ConnectionError, RequestsConnectionError, RequestsTimeout) as e:
        retry_data = self.request.properties.get('retry_spec')
        if not retry_data:
            raise
        else:
            max_retries, countdown = get_retry_parameters(self.request.retries, retry_data)
            if max_retries == 0:
                raise
            retry_data['_countdown_'] = countdown
            self.retry(exc=e, max_retries=max_retries, countdown=countdown, retry_spec=retry_data)
