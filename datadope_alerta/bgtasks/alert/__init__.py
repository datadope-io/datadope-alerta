import random
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

# noinspection PyPackageRequirements
from celery.utils.time import get_exponential_backoff_interval
from requests.exceptions import ConnectionError as RequestsConnectionError, Timeout as RequestsTimeout

from alerta.models.metrics import Timer
from datadope_alerta import BGTaskAlerterDataConstants as BGTadC, ContextualConfiguration, GlobalAttributes
from datadope_alerta import DateTime, thread_local, ALERTERS_KEY_BY_OPERATION
from datadope_alerta.backend.flexiblededup.models.alerters import AlerterOperationData
from datadope_alerta.plugins import Alerter, AlerterStatus, RetryableException
from .. import app, celery, getLogger, Alert
# noinspection PyUnresolvedReferences
from .. import revoke_task  # To provide import to package modules


class AlertTask(celery.Task, ABC):
    ignore_result = True
    _time_management = {}
    _recovery_task = None
    _action_task = None

    def __init__(self):
        super().__init__()
        self.logger = getLogger(self.__module__)

    @staticmethod
    @abstractmethod
    def get_operation() -> str:
        pass

    @abstractmethod
    def before_start_operation(self, task_id, alerter_operation_data: AlerterOperationData,
                               current_status, kwargs) -> AlerterStatus:
        pass

    @abstractmethod
    def on_success_operation(self, alerter_operation_data: AlerterOperationData,
                             current_status, kwargs) -> AlerterStatus:
        pass

    @abstractmethod
    def on_failure_operation(self, task_id, alerter_operation_data: AlerterOperationData,
                             current_status, retval, kwargs) -> Optional[AlerterStatus]:
        pass

    @abstractmethod
    def on_retry_operation(self, task_id, alerter_operation_data: AlerterOperationData,
                           current_status, exc, einfo, kwargs) -> bool:
        """

        :param task_id:
        :param alerter_operation_data:
        :param current_status:
        :param exc:
        :param einfo:
        :param kwargs:
        :return: True if operation might be retried
          (other considerations as no more retries left may make the alert not be retried
          even if this method returns True)
        """
        pass

    @classmethod
    def get_recovery_task(cls) -> 'RecoveryTask':
        if cls._recovery_task is None:
            from .. import recovery_task
            cls._recovery_task = recovery_task
        return cls._recovery_task

    @classmethod
    def get_action_task(cls) -> 'ActionTask':
        if cls._action_task is None:
            from .. import action_task
            cls._action_task = action_task
        return cls._action_task

    @staticmethod
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

    @staticmethod
    def _get_alerter(alerter_data, task):
        alerter_name = alerter_data[BGTadC.NAME]
        alerter_class = alerter_data[BGTadC.CLASS]
        return Alerter.get_alerter_type(alerter_class)(alerter_name, task)

    @classmethod
    def _get_parameters(cls, kwargs):  # task_id null for intermediate requests => begin time is not popped
        alerter_data = kwargs['alerter_data']
        alert_id = kwargs['alert_id']
        action_ = kwargs.get('action')
        alerter_name = alerter_data[BGTadC.NAME]
        operation = cls.get_operation()
        operation_key = action_ or ALERTERS_KEY_BY_OPERATION[operation]
        return alert_id, alerter_name, operation, operation_key

    @classmethod
    def _get_timing_from_now(cls, task_id):
        """
        Returns task begin time if available, finish time == now and duration (if begin time is available).

        :param task_id:
        :return:
        """
        now = datetime.utcnow()
        duration = 0.0
        begin = cls._time_management.get(task_id, None)
        if begin:
            duration = (now - begin).total_seconds()
        return begin, now, duration

    @classmethod
    def _update_alerter_db_info(cls, status: AlerterStatus,
                                alerter_operation_data: AlerterOperationData):
        alerter_operation_data.task_chain_info = None
        AlerterStatus.store(alerter_operation_data.alert_id, alerter_operation_data.alerter, status=status)
        alerter_operation_data.store()

    def _finish_task(self, alerter_operation_data: AlerterOperationData, status, retval, start_time,
                     end_time):
        if start_time is None:
            start_time = alerter_operation_data.start_time
        if start_time is not None and end_time is not None:
            duration = DateTime.diff_seconds_utc(end_time, start_time)
        else:
            duration = 0.0
        alerter_operation_data = Alerter.prepare_result(alerter_operation_data=alerter_operation_data, retval=retval,
                                                        start_time=start_time, end_time=end_time,
                                                        retries=self.request.retries)
        self.logger.info("PROCESS FINISHED IN %.3f sec. RESULT %s -> %s",
                         duration, 'SUCCESS' if alerter_operation_data.success else 'FAILURE', retval)
        self._update_alerter_db_info(status, alerter_operation_data)


    def before_start(self, task_id, args, kwargs):  # noqa
        start_time = datetime.utcnow()
        alert_id, alerter_name, operation, operation_key = self._get_parameters(kwargs)
        thread_local.alert_id = alert_id
        thread_local.alerter_name = alerter_name
        thread_local.operation = operation_key
        is_retrying = self.request.retries > 0
        if is_retrying:
            self.logger.info("Retry %d", self.request.retries)
        else:
            self._time_management[task_id] = start_time
            self.logger.info("Starting task")
        with app.app_context():
            current_status = AlerterStatus.from_db(alert_id, alerter_name)
            alerter_operation_data = AlerterOperationData.from_db(alert_id, alerter_name, operation_key)
            new_status = self.before_start_operation(task_id, alerter_operation_data,
                                                     current_status, kwargs)
            if is_retrying:
                alerter_operation_data.retries = self.request.retries
            else:
                alerter_operation_data.start_time = start_time
                if alerter_operation_data.received_time is None:
                    alerter_operation_data.received_time = alerter_operation_data.start_time
            AlerterStatus.store(alert_id, alerter_name, new_status)
            alerter_operation_data.store()

    def on_success(self, retval, task_id, args, kwargs):  # noqa
        try:
            alert_id, alerter_name, operation, operation_key = self._get_parameters(kwargs)
            start_time, end_time, duration = self._get_timing_from_now(task_id)
            with app.app_context():
                current_status = AlerterStatus.from_db(alert_id, alerter_name)
                alerter_operation_data = AlerterOperationData.from_db(alert_id, alerter_name, operation_key)
                next_status = self.on_success_operation(alerter_operation_data, current_status, kwargs)
                self._finish_task(alerter_operation_data=alerter_operation_data, status=next_status, retval=retval,
                                  start_time=start_time, end_time=end_time)
        finally:
            self._time_management.pop(task_id, None)

    def on_failure(self, exc, task_id, args, kwargs, einfo):  # noqa
        try:
            include_traceback = self.request.properties.get('include_traceback', False)
            retval = False, Alerter.result_for_exception(exc, einfo, include_traceback=include_traceback)
            alert_id, alerter_name, operation, operation_key = self._get_parameters(kwargs)
            start_time, end_time, duration = self._get_timing_from_now(task_id)
            with app.app_context():
                current_status = AlerterStatus.from_db(alert_id, alerter_name)
                alerter_operation_data = AlerterOperationData.from_db(alert_id, alerter_name, operation_key)
                next_status = self.on_failure_operation(task_id=task_id, alerter_operation_data=alerter_operation_data,
                                                        current_status=current_status, retval=retval, kwargs=kwargs)
                if next_status:
                    self._finish_task(alerter_operation_data=alerter_operation_data, status=next_status, retval=retval,
                                      start_time=start_time, end_time=end_time)
        finally:
            self._time_management.pop(task_id, None)

    def on_retry(self, exc, task_id, args, kwargs, einfo):  # noqa
        alert_id, alerter_name, operation, operation_key = self._get_parameters(kwargs)
        with app.app_context():
            current_status = AlerterStatus.from_db(alert_id, alerter_name)
            alerter_operation_data = AlerterOperationData.from_db(alert_id, alerter_name, operation_key)
            should_retry = self.on_retry_operation(task_id=task_id, alerter_operation_data=alerter_operation_data,
                                                   current_status=current_status,
                                                   exc=exc, einfo=einfo, kwargs=kwargs)
        if should_retry:
            countdown = self.request.properties.get('retry_spec', {}).get('_countdown_', 0.0)
            self.logger.info("SCHEDULED RETRY %d/%d IN %.0f secs -> %s",
                             self.request.retries + 1, self.override_max_retries, countdown, exc)
        else:
            revoke_task(task_id)

    # noinspection PyShadowingNames
    def run(self, alerter_data: dict, alert_id: str, reason: Optional[str], action: str = None):
        alerter = self._get_alerter(alerter_data, self)
        operation = self.get_operation()
        operation_key = action or ALERTERS_KEY_BY_OPERATION[operation]
        self.logger.info("Running background task")
        bg_timer = Timer('alerters', f"{alerter.name}_{operation_key}",
                         f"{alerter.name} {operation_key}",
                         f"Total time and number of alerter {alerter.name} operation {operation_key}")
        ts = bg_timer.start_timer()
        do_not_retry = False
        try:
            alert = Alert.find_by_id(alert_id)
            do_not_retry_tag = ContextualConfiguration.get_global_configuration(GlobalAttributes.DO_NOT_RETRY_TAG)
            do_not_retry = do_not_retry_tag in alert.tags
            parameters = [alert, reason]
            if action:
                parameters.append(action)
            response = getattr(alerter, operation)(*parameters)
            return response
        except (RetryableException, ConnectionError, RequestsConnectionError, RequestsTimeout) as e:
            retry_data = self.request.properties.get('retry_spec')
            if not retry_data or do_not_retry:
                raise
            else:
                max_retries, countdown = self.get_retry_parameters(self.request.retries, retry_data)
                if max_retries == 0:
                    raise
                retry_data['_countdown_'] = countdown
                self.retry(exc=e, max_retries=max_retries, countdown=countdown, retry_spec=retry_data)
        finally:
            bg_timer.stop_timer(ts)

# Tasks defined as classes must be instantiated and registered

from .event import Task as EventTask  # noqa
event_task = EventTask()
celery.register_task(event_task)

from .recovery import Task as RecoveryTask # noqa
recovery_task = RecoveryTask()
celery.register_task(recovery_task)

from .repeat import Task as RepeatTask  # noqa
repeat_task = RepeatTask()
celery.register_task(repeat_task)

from .action import Task as ActionTask  # noqa
action_task = ActionTask()
celery.register_task(action_task)
