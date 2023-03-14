import random
from datetime import datetime, timedelta
from importlib import import_module
from math import floor
from typing import Union, Dict

# noinspection PyPackageRequirements
from celery import signature
from requests.exceptions import ConnectionError as RequestsConnectionError, Timeout as RequestsTimeout

from alerta.exceptions import AlertaException
from alerta.models.enums import Status

from iometrics_alerta import DateTime, RecoveryActionsFields, thread_local
from iometrics_alerta import GlobalAttributes
from iometrics_alerta.backend.flexiblededup.models.recovery_actions import RecoveryActionData, RecoveryActionsStatus
from iometrics_alerta.plugins import RetryableException, result_for_exception
from . import app, celery, getLogger, Alert
from . import revoke_task  # noqa - Provide import to other classes
from ..recovery_actions.providers import RecoveryActionsProvider, RecoveryActionsResponseStatus, RecoveryActionsResponse

logger = getLogger(__name__)


def load_instance(instance_class, *args) -> RecoveryActionsProvider:
    module_name, _, class_name = instance_class.partition(':')
    module = import_module(module_name)
    return getattr(module, class_name)(*args)


def load_alerter_plugin(alerter_name, instance_class):
    plugin_object = load_instance(instance_class)
    plugin_object.alerter_name = alerter_name
    plugin_object.global_app_config = app.config
    return plugin_object


def get_alerter_plugins_objects(alerter_plugins: Dict[str, str]) -> dict:
    return {x: load_alerter_plugin(x, y) for x, y in alerter_plugins.items()}


def launch_alerters(alert, recovery_actions_config, alerter_plugins: Dict[str, str]):
    if alert.status in (Status.Closed, Status.Expired):
        logger.info("Cancelling launching alerters on a closed or expired alert")
        return
    alerter_plugins_objs = get_alerter_plugins_objects(alerter_plugins)
    alerters = recovery_actions_config[RecoveryActionsFields.ALERTERS.var_name]
    logger.info("Launching alerting to alerters: '%s'", ', '.join(alerters))
    alert = do_alert(alert, alerters, app.config, alerter_plugins_objs)
    alert.update_attributes(alert.attributes)


def do_alert(alert, alerters, config, alerter_plugins: dict, repeating=False) -> Alert:
    for alerter in alerters:
        if alerter not in alerter_plugins:
            logger.error("Unregistered alerter plugin '%s'", alerter)
            continue
        plugin = alerter_plugins[alerter]
        updated = None
        try:
            updated = plugin.post_receive(alert, config=config, ignore_delay=True, force_repeat=repeating)
        except TypeError:
            updated = plugin.post_receive(alert)  # for backward compatibility
        except AlertaException:
            raise
        except Exception as e:
            if config.get('PLUGINS_RAISE_ON_ERROR', True):
                raise Exception(f"[Alert '{alert.id}']: Error while running post-receive plugin '{plugin.name}':"
                                f" {str(e)}")
            else:
                logger.error(f"Error while running post-receive plugin '{plugin.name}':"
                             f" {str(e)}")
        if updated:
            alert = updated
            alert.update_attributes(alert.attributes)
    return alert


@celery.task(base=celery.Task, bind=True, ignore_result=True)
def launch_actions(self, alert_id: str, provider_name, provider_class: str, alerter_plugins: Dict[str, str],
                   operation_id=None):
    thread_local.alert_id = alert_id
    thread_local.alerter_name = provider_name
    thread_local.operation = 'recovery_actions'
    begin = datetime.now()
    alert = Alert.find_by_id(alert_id)
    if alert.status in (Status.Closed, Status.Expired):
        logger.info("Cancelling execution of recovery actions on a closed or expired alert")
        return
    logger.info("Executing recovery actions")
    recovery_actions_config = alert.attributes[GlobalAttributes.RECOVERY_ACTIONS.var_name]
    recovery_actions_data = RecoveryActionData.from_db(alert_id=alert_id)
    current_retries = recovery_actions_data.retries
    if current_retries is None:
        current_retries = 0
        recovery_actions_data.start_time = datetime.utcnow()
    else:
        current_retries += 1
    recovery_actions_data.retries = current_retries
    try:
        provider = load_instance(provider_class, provider_name, app.config)
        recovery_actions_data.store()
        response = provider.execute_actions(alert,
                                            recovery_actions_config[RecoveryActionsFields.ACTIONS.var_name],
                                            recovery_actions_config[RecoveryActionsFields.EXTRA_CONFIG.var_name],
                                            operation_id)
        if response.status == RecoveryActionsResponseStatus.RESPONSE_OK:
            if response.operation_id:
                recovery_actions_data.job_id = response.operation_id
            alert = wait_for_recovery(alert, recovery_actions_config, recovery_actions_data, response, alerter_plugins)
        elif response.status == RecoveryActionsResponseStatus.WAITING_RESPONSE:
            operation_id = response.operation_id
            if not operation_id:
                raise RetryableException(f"[Alert '%s']: Missing operation_id in an async"
                                         f" recovery actions provider result")
            recovery_actions_data.job_id = response.operation_id
            wait_for_response(alert, provider_name, provider_class, alerter_plugins, operation_id,
                              recovery_actions_config, recovery_actions_data)
        else:
            if response.operation_id:
                recovery_actions_data.job_id = response.operation_id
            raise RetryableException(response)
    except (RetryableException, ConnectionError, RequestsConnectionError, RequestsTimeout) as e:
        retry_or_finish(self, alert, e, recovery_actions_config,
                        recovery_actions_data, alerter_plugins, begin)
    except Exception as e:
        retry_or_finish(self, alert, e, recovery_actions_config,
                        recovery_actions_data, alerter_plugins, begin, no_retries=True)
    finally:
        recovery_actions_data.store()


def get_job_retry_delay(recovery_actions_config):
    retry_interval = recovery_actions_config[RecoveryActionsFields.JOB_RETRY_INTERVAL.var_name]
    random_part = random.random() * retry_interval
    retry_at = retry_interval / 2 + random_part
    return retry_at


def relaunch_actions(alert, provider_name, provider_class, alerter_plugins: Dict[str, str],
                     recovery_actions_data: RecoveryActionData,
                     recovery_actions_config, response, operation_id):
    consumed_retries = recovery_actions_data.retries or 0
    max_retries = recovery_actions_config[RecoveryActionsFields.MAX_RETRIES.var_name]
    queue = recovery_actions_config[RecoveryActionsFields.TASK_QUEUE.var_name]
    countdown = get_job_retry_delay(recovery_actions_config)
    if consumed_retries < max_retries:
        logger.warning("Job' %s' for recovery actions failed: %s."
                       " Scheduled job retry %d/%d in %.1f seconds",
                       operation_id, response.response_data, consumed_retries+1, max_retries, countdown)
        kwargs = {
            'alert_id': alert.id,
            'provider_name': provider_name,
            'provider_class': provider_class,
            'alerter_plugins': alerter_plugins,
            'operation_id': operation_id
        }
        task = signature(launch_actions, args=[], kwargs=kwargs).apply_async(
            countdown=countdown, queue=queue, retries=consumed_retries,
            retry_spec={'max_retries': max_retries})
        recovery_actions_data.bg_task_id = task.id
    else:
        logger.warning("Error executing recovery actions. No more retries")
        finish_launching_alerters(alert, response, recovery_actions_config, recovery_actions_data, alerter_plugins,
                                  begin=None, retries=max_retries)


@celery.task(base=celery.Task, bind=True, ignore_result=True)
def request_async_status(self, alert_id: str, provider_name, provider_class: str, alerter_plugins: Dict[str, str],
                         operation_id):
    thread_local.alert_id = alert_id
    thread_local.alerter_name = provider_name
    thread_local.operation = 'recovery_actions'
    alert = Alert.find_by_id(alert_id)
    if alert.status in (Status.Closed, Status.Expired):
        logger.info("Cancelling requesting recovery operation status on a closed or expired alert")
        return
    logger.info("Requesting recovery actions execution status for operation '%s'", operation_id)
    recovery_actions_config = alert.attributes[GlobalAttributes.RECOVERY_ACTIONS.var_name]
    recovery_actions_data = RecoveryActionData.from_db(alert_id=alert_id)
    try:
        provider = load_instance(provider_class, provider_name, app.config)
        response = provider.get_execution_status(alert_id=alert.id, operation_id=operation_id)
        if response.status == RecoveryActionsResponseStatus.RESPONSE_OK:
            alert = wait_for_recovery(alert, recovery_actions_config, recovery_actions_data, response, alerter_plugins)
        elif response.status == RecoveryActionsResponseStatus.WAITING_RESPONSE:
            raise RetryableException("Provider has not finished executing actions")
        else:
            relaunch_actions(alert, provider_name, provider_class, alerter_plugins, recovery_actions_data,
                             recovery_actions_config, response, operation_id)
    except (RetryableException, ConnectionError, RequestsConnectionError, RequestsTimeout) as e:
        retry_spec = self.request.properties['retry_spec']
        max_retries = retry_spec['max_retries']
        if self.request.retries < max_retries:
            countdown = recovery_actions_config[RecoveryActionsFields.STATUS_REQUEST_INTERVAL.var_name]
            logger.info("%s. Scheduled retry %d/%d in %.1f seconds",
                        e, self.request.retries + 1, max_retries, countdown)
            self.retry(exc=e, countdown=countdown, max_retries=max_retries, retry_spec=retry_spec)
        else:
            logger.warning("Error executing recovery actions: %s in time", e)
            finish_launching_alerters(alert, e, recovery_actions_config,
                                      recovery_actions_data, alerter_plugins)
    except Exception as e:
        logger.warning("Error executing recovery actions: %s", e)
        finish_launching_alerters(alert, e, recovery_actions_config,
                                  recovery_actions_data, alerter_plugins)
    finally:
        recovery_actions_data.store()


def wait_for_response(alert: Alert, provider_name: str, provider_class: str, alerter_plugins: Dict[str, str],
                      operation_id, recovery_actions_config, recovery_actions_data: RecoveryActionData):
    timeout_for_response = recovery_actions_config[RecoveryActionsFields.TIMEOUT_FOR_RESPONSE.var_name]
    status_request_interval = recovery_actions_config[RecoveryActionsFields.STATUS_REQUEST_INTERVAL.var_name]
    retries = floor(timeout_for_response / status_request_interval)
    logger.info("Recovery actions not finished. Requesting status every %.0f seconds."
                " Timeout after %d retries", status_request_interval, retries)
    properties = {
        'countdown': status_request_interval,
        'queue': recovery_actions_config[RecoveryActionsFields.STATUS_QUEUE.var_name],
        'retry_spec': {'max_retries': retries}
    }
    kwargs = {
        'alert_id': alert.id,
        'provider_name': provider_name,
        'provider_class': provider_class,
        'alerter_plugins': alerter_plugins,
        'operation_id': operation_id
    }
    task = signature(request_async_status, args=[], kwargs=kwargs).apply_async(**properties)
    recovery_actions_data.bg_task_id = task.id


def wait_for_recovery(alert: Alert, recovery_actions_config, recovery_actions_data: RecoveryActionData,
                      response: RecoveryActionsResponse,
                      alerter_plugins: Dict[str, str]):
    fill_result(recovery_actions_data, response, status=RecoveryActionsStatus.WaitingResolution)
    finish_time = response.finish_time or DateTime.make_aware_utc(datetime.now())
    timeout = recovery_actions_config[RecoveryActionsFields.TIMEOUT_FOR_RESOLUTION.var_name]
    eta = finish_time + timedelta(seconds=timeout)
    diff = DateTime.diff_seconds_utc(eta, datetime.now())
    logger.info("Recovery actions sent successfully. Waiting %.0f seconds for recovery", diff)
    properties = {
        'eta': eta,
        'queue': recovery_actions_config[RecoveryActionsFields.WAIT_QUEUE.var_name],
        'retry': False
    }
    kwargs = {
        'alert_id': alert.id,
        'alerter_plugins': alerter_plugins,
    }
    task = signature(fail_not_resolved, args=[], kwargs=kwargs).apply_async(**properties)
    recovery_actions_data.bg_task_id = task.id
    alerters_always = recovery_actions_config.get(RecoveryActionsFields.ALERTERS_ALWAYS.var_name, [])
    # Repeat event is forced in alerters invoked before, as recovery action providers may have enriched the alert
    # information
    if alerters_always:
        alerter_plugins_objs = get_alerter_plugins_objects(alerter_plugins)
        alert = do_alert(alert, alerters_always, app.config, alerter_plugins_objs, repeating=True)
    return alert


@celery.task(ignore_result=True, max_retries=0)
def fail_not_resolved(alert_id: str, alerter_plugins: Dict[str, str]):
    thread_local.alert_id = alert_id
    thread_local.operation = 'recovery_actions'
    # If here, alert is not closed. But check anyway
    alert = Alert.find_by_id(alert_id)
    if alert.status not in (Status.Closed, Status.Expired):
        logger.info("Alert not recovered in time after recovery actions")
        recovery_actions_config = alert.attributes[GlobalAttributes.RECOVERY_ACTIONS.var_name]
        recovery_actions_data = RecoveryActionData.from_db(alert_id=alert_id)
        finish_launching_alerters(alert, Exception("Alert not resolved in time after recovery actions"),
                                  recovery_actions_config, recovery_actions_data, alerter_plugins)
        recovery_actions_data.store()


def finish_launching_alerters(alert, response: RecoveryActionsResponse | Exception, recovery_actions_config,
                              recovery_actions_data: RecoveryActionData, alerter_plugins: Dict[str, str],
                              begin=None, retries=0):
    fill_result(recovery_actions_data, response, begin=begin, retries=retries)
    recovery_actions_data.alerting_time = datetime.utcnow()
    launch_alerters(alert, recovery_actions_config, alerter_plugins)


def retry_or_finish(task, alert, exc: Exception,
                    recovery_actions_config, recovery_actions_data, alerter_plugins: Dict[str, str],
                    begin=None, no_retries=False):
    retry_spec = task.request.properties['retry_spec']
    max_retries = retry_spec['max_retries']
    if not no_retries and task.request.retries < max_retries:
        countdown = get_job_retry_delay(recovery_actions_config)
        logger.warning("Error executing recovery actions: %s. Scheduled Retry %d/%d in %.1f seconds",
                       exc, task.request.retries + 1, max_retries, countdown)
        task.retry(exc=exc, countdown=countdown, max_retries=max_retries, retry_spec=retry_spec)
    else:
        logger.warning("Error executing recovery actions: %s%s",
                       exc, "" if no_retries else ". No more retries")
        finish_launching_alerters(alert, exc, recovery_actions_config, recovery_actions_data, alerter_plugins, begin,
                                  task.request.retries)


def fill_result(recovery_action_data: RecoveryActionData,
                response: Union[RecoveryActionsResponse, Exception],
                status=RecoveryActionsStatus.Finished,
                begin=None, end=None, retries=0):
    if not end:
        end = datetime.utcnow()
    begin = recovery_action_data.start_time or begin or end
    recovery_action_data.start_time = recovery_action_data.start_time or begin
    if isinstance(response, Exception) and response.args and isinstance(response.args[0], RecoveryActionsResponse):
        response = response.args[0]
    response_data, success = (result_for_exception(exc=response), False) if isinstance(response, Exception) \
        else (response.response_data, response.status == RecoveryActionsResponseStatus.RESPONSE_OK)
    recovery_action_data.status = status
    recovery_action_data.end_time = end
    recovery_action_data.success = success
    recovery_action_data.response = response_data
    if retries > 0:
        recovery_action_data.retries = retries
    return recovery_action_data
