import logging
import random
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Optional, Type, List, Tuple, Callable

from alerta.models.alert import Alert
from alerta.models.enums import Status, Action
from alerta.plugins import PluginBase

from iometrics_alerta import DateTime, get_config, thread_local, AlertIdFilter, ALERTERS_KEY_BY_OPERATION
from iometrics_alerta import BGTaskAlerterDataConstants as BGTadC
# noinspection PyPep8Naming
from iometrics_alerta import ContextualConfiguration as CC, GlobalAttributes as GAttr
from . import Alerter, AlerterStatus, AlerterOperationData


_alert_task_by_operation = {}


def get_alert_task_by_operation(operation):
    global _alert_task_by_operation
    if not _alert_task_by_operation:
        from .bgtasks import event_task, recovery_task, repeat_task, action_task
        _alert_task_by_operation.update({
            Alerter.process_event.__name__: event_task,
            Alerter.process_recovery.__name__: recovery_task,
            Alerter.process_action.__name__: action_task,
            Alerter.process_repeat.__name__: repeat_task
        })
    return _alert_task_by_operation[operation]


def revoke_task(task_id):
    from .bgtasks import revoke_task
    revoke_task(task_id)


class IOMAlerterPlugin(PluginBase, ABC):

    def __init__(self, name=None):
        name = name or self.__module__.rsplit('.', 1)[0]
        super(IOMAlerterPlugin, self).__init__(name)
        self.logger = logging.getLogger(self.name)
        self.logger.addFilter(AlertIdFilter.get_instance())
        self.__global_app_config = None
        self.__alerter_name = None
        self.__alerter_config = None

    # noinspection PyShadowingBuiltins
    def get_config(self, key, default=None, type=None, config=None):
        return get_config(key, default, type, self.global_app_config if config is None else config)

    @abstractmethod
    def get_alerter_class(self) -> Type[Alerter]:
        pass

    # noinspection PyMethodMayBeStatic
    def register_periodic_tasks(self, config) -> List[Tuple[Callable, float]]:
        return []

    @property
    def global_app_config(self):
        if self.__global_app_config is None:
            raise Exception("Application config required before stored in plugin '%s'", self.name)
        return self.__global_app_config

    @global_app_config.setter
    def global_app_config(self, new_config):
        self.__global_app_config = new_config

    @property
    def alerter_name(self) -> str:
        if self.__alerter_name is None:
            self.__alerter_name = self.name.replace('.', '_').replace('$', '_')
        return self.__alerter_name

    @alerter_name.setter
    def alerter_name(self, new_alerter_name):
        new_alerter_name = new_alerter_name.replace('.', '_').replace('$', '_')
        if self.__alerter_name is not None:
            if new_alerter_name != self.__alerter_name:
                self.logger.warning("Alerter name cannot be modified once assigned for plugin '%s'."
                                    " Keeping assigned name: '%s'", self.name, self.__alerter_name)
            return
        self.__alerter_name = new_alerter_name

    @property
    def alerter_data(self) -> Dict[str, Any]:
        return {
            BGTadC.NAME: self.alerter_name,
            BGTadC.CLASS: Alerter.get_fullname(self.get_alerter_class()),
            BGTadC.PLUGIN: self.name
        }

    def get_alerter_status_for_alert(self, alert):
        return AlerterStatus.from_db(alert_id=alert.id, alerter_name=self.alerter_name)

    def has_alerting_succeeded(self, alert):
        return AlerterOperationData.has_alerting_succeeded(alert.id, self.alerter_name)

    def get_task_specification(self, alert, operation):
        return defaultdict(dict, CC.get_contextual_global_config(CC.TASKS_DEFINITION, alert, self,
                                                                 operation=operation)[0])

    def get_processing_delay(self, alert, operation):
        now = datetime.utcnow()
        create_time = alert.create_time or now
        consumed_time = DateTime.diff_seconds_utc(now, create_time)
        delay = CC.get_contextual_global_config(CC.ACTION_DELAY, alert, self, operation)[0]
        return max(0, delay - consumed_time)

    def _prepare_begin_processing(self, alert, alerter_operation_data, is_recovering, is_actioning,
                                  is_repeating, new_event_status: AlerterStatus, reason):
        begin = datetime.utcnow()
        if is_recovering:
            operation = Alerter.process_recovery.__name__
            new_status = AlerterStatus.Recovering
            delay = 5.0
        elif is_actioning:
            operation = Alerter.process_action.__name__
            new_status = AlerterStatus.Actioning
            delay = 5.0
        elif is_repeating:
            operation = Alerter.process_repeat.__name__
            new_status = AlerterStatus.Repeating
            delay = 5.0
        else:
            new_status = new_event_status
            operation = Alerter.process_event.__name__
            delay = self.get_processing_delay(alert, operation)
        delay = max(5.0, delay) + random.uniform(-2.0, 5.0)
        alerter_operation_data.received_time = begin
        reason = reason or CC.get_contextual_global_config(CC.REASON, alert, self, operation)[0]
        alerter_operation_data.reason = reason
        return new_status, begin, delay

    @staticmethod
    def _prepare_recovery_special_result(alert_operation_data: AlerterOperationData, result_data, start_time):
        alert_operation_data.received_time = start_time
        alert_operation_data.success = True
        alert_operation_data.response = result_data
        alert_operation_data.skipped = True

    def _get_last_repeat_time(self, alert):
        alerter_operation_data = AlerterOperationData.from_db(
            alert_id=alert.id, alerter=self.alerter_name,
            operation=ALERTERS_KEY_BY_OPERATION[Alerter.process_repeat.__name__])
        if time := alerter_operation_data.received_time:
            return time

        alerter_operation_data = AlerterOperationData.from_db(
            alert_id=alert.id, alerter=self.alerter_name,
            operation=ALERTERS_KEY_BY_OPERATION[Alerter.process_event.__name__])
        if time := alerter_operation_data.received_time:
            return time
        return datetime.utcnow()

    def _prepare_post_receive(self, alert, new_event_status: AlerterStatus, kwargs):
        self.global_app_config = kwargs['config']
        reopening = kwargs.get('reopening')
        status = Status.Open if reopening else alert.status
        force_recovery = kwargs.get('force_recovery', False)
        force_repeat = kwargs.get('force_repeat', False)
        force_action = kwargs.get('force_action')
        alerter_operation_data = None
        operation = None
        recovering = force_recovery or status == Status.Closed
        if recovering:
            operation = Alerter.process_recovery.__name__
            operation_key = ALERTERS_KEY_BY_OPERATION[operation]
            thread_local.operation = operation_key
            alerter_operation_data = AlerterOperationData.from_db(alert.id, self.alerter_name, operation_key)
        actioning = not force_recovery and force_action
        if actioning:
            operation = Alerter.process_action.__name__
            operation_key = force_action
            thread_local.operation = operation_key
            # Actioning => one record for each action. Force creating new record
            alerter_operation_data = AlerterOperationData(alert.id, self.alerter_name, operation_key)
        alerter_status = self.get_alerter_status_for_alert(alert)
        repeating = not recovering and not actioning and alerter_status == AlerterStatus.Processed
        if repeating:
            operation = Alerter.process_repeat.__name__
            operation_key = ALERTERS_KEY_BY_OPERATION[operation]
            thread_local.operation = operation_key
            # Repeating => one record for each repeat. Force creating new record
            alerter_operation_data = AlerterOperationData(alert.id, self.alerter_name, operation_key)
        if repeating and not force_repeat:
            # Is repeating but check if the interval is good
            success = self.has_alerting_succeeded(alert)
            if success:
                repeating_interval = CC.get_contextual_global_config(CC.REPEAT_MIN_INTERVAL, alert, self)[0]
                if repeating_interval:
                    last_repetition = self._get_last_repeat_time(alert)
                    now = datetime.utcnow()
                    repeating = (now - last_repetition).total_seconds() > repeating_interval
                    if not repeating:
                        self.logger.debug("Not repeating. Interval among repetitions not reached.")
                else:
                    repeating = False
                    self.logger.debug("Not repeating. Repetition is deactivated.")
            else:
                self.logger.debug("Not repeating a failed alerting")
                repeating = False
        if alert.repeat and not recovering and not actioning and not repeating and alerter_status != AlerterStatus.New:
            self.logger.info("Ignoring repetition")
            return None
        if not recovering and not actioning and not repeating:
            operation = Alerter.process_event.__name__
            operation_key = ALERTERS_KEY_BY_OPERATION[operation]
            thread_local.operation = operation_key
            alerter_operation_data = AlerterOperationData.from_db(alert.id, self.alerter_name, operation_key)
        self.logger.debug("Entering post_receive method")
        reason = kwargs.get('reason') or alert.text
        new_status, begin, delay = self._prepare_begin_processing(
            alert, alerter_operation_data, is_recovering=recovering, is_actioning=actioning, is_repeating=repeating,
            new_event_status=new_event_status, reason=reason)
        return alerter_operation_data, new_status, begin, delay, operation, reason

    #
    # PluginBase ABSTRACT METHODS IMPLEMENTATION
    #
    def pre_receive(self, alert: Alert, **kwargs) -> Alert:
        thread_local.alert_id = alert.id
        thread_local.alerter_name = self.alerter_name
        self.global_app_config = kwargs['config']
        self.logger.debug("Ignoring pre_receive")
        thread_local.alerter_name = None
        thread_local.operation = None
        return alert

    def post_receive(self, alert: Alert, **kwargs) -> Optional[Alert]:
        """
        Supported kwargs:
          * config: used by Alerta. Always expected.
          * force_recovery: If True consider always a recovery operation.
          * ignore_delay: if True, background task will be executed immediately (after 2 seconds).
          * reason: reason of the invocation. May be used by alerters recovery operations.

        :param alert:
        :param kwargs:
        :return:
        """
        thread_local.alert_id = alert.id
        thread_local.alerter_name = self.alerter_name
        try:
            post_receive_data = self._prepare_post_receive(alert, AlerterStatus.Scheduled, kwargs)
            if post_receive_data:
                alerter_operation_data, status, begin, delay, operation, reason = post_receive_data
                delay = 2 if kwargs.get('ignore_delay', False) else delay
            else:
                return None

            store_traceback = CC.get_contextual_global_config(CC.STORE_TRACEBACK_ON_EXCEPTION,
                                                              alert, self, operation)[0]
            try:
                task_specification = self.get_task_specification(alert, operation)
                task_instance = get_alert_task_by_operation(operation)
                task = task_instance.apply_async(
                    kwargs=dict(alerter_data=self.alerter_data, alert=alert, reason=reason,
                                action=kwargs.get('force_action')),
                    countdown=round(delay), **task_specification, include_traceback=store_traceback)
                self.logger.info("Scheduled task '%s' to run in %.0f seconds in queue '%s'",
                                 task.id, delay, task_specification.get('queue', '<default>'))
                alerter_operation_data.bg_task_id = task.id
            except Exception as e:
                self.logger.error("Error executing post_receive: %s", e, exc_info=e)
                now = datetime.utcnow()
                retval = False, Alerter.result_for_exception(e, include_traceback=store_traceback)
                status = AlerterStatus.Recovered if operation == Alerter.process_recovery.__name__ \
                    else AlerterStatus.Processed
                alerter_operation_data = Alerter.prepare_result(alerter_operation_data, retval, begin, now)

            AlerterStatus.store(alert.id, self.alerter_name, status)
            alerter_operation_data.store()
            return alert
        finally:
            thread_local.alerter_name = None
            thread_local.operation = None

    def status_change(self, alert: Alert, status, text: str, **kwargs) -> Any:
        thread_local.alert_id = alert.id
        thread_local.alerter_name = self.alerter_name
        try:
            self.global_app_config = kwargs['config']
            current_status = Status(alert.status)
            if status == current_status:
                return None
            alerter_status = self.get_alerter_status_for_alert(alert)
            if status == Status.Open and alerter_status == AlerterStatus.New:
                self.logger.info("Alert has been reopen. Processed as new")
                return self.post_receive(alert, reopening=True, **kwargs)
            if status == Status.Closed:
                operation = Alerter.process_recovery.__name__
                operation_key = ALERTERS_KEY_BY_OPERATION[operation]
                thread_local.operation = operation_key
                start_time = datetime.utcnow()
                alerter_operation_data = AlerterOperationData.from_db(alert.id, self.alerter_name, operation_key)
                ignore_recovery, level = CC.get_contextual_global_config(CC.IGNORE_RECOVERY, alert, self)
                if alerter_status == AlerterStatus.Scheduled:
                    alerter_operation_data_new = AlerterOperationData.from_db(
                        alert.id, self.alerter_name, ALERTERS_KEY_BY_OPERATION[Alerter.process_event.__name__])
                    bgtask_id = alerter_operation_data_new.bg_task_id
                    if bgtask_id:
                        revoke_task(bgtask_id)
                        self.logger.info("Status changed to closed while waiting to alert. Revoking alert task %s.",
                                         bgtask_id)
                    else:
                        self.logger.warning("BGTASK ID NOT FOUND")
                    result_data = {"info": {"message": "RECOVERED BEFORE ALERTING"}}
                    new_alerter_status = AlerterStatus.Recovered
                    self._prepare_recovery_special_result(alerter_operation_data, result_data, start_time)
                    alerter_operation_data_new.success = True
                    alerter_operation_data_new.response = result_data
                    alerter_operation_data_new.skipped = True
                    AlerterStatus.store(alert.id, self.alerter_name, new_alerter_status)
                    alerter_operation_data_new.store()
                    alerter_operation_data.store()
                    return alert, status, text
                elif ignore_recovery:
                    self.logger.info("Ignoring recovery configured with context '%s'", level.value)
                    result_data = {"info": {"message": "IGNORED RECOVERY"}}
                    new_alerter_status = AlerterStatus.Recovered
                    self._prepare_recovery_special_result(alerter_operation_data, result_data, start_time)
                    AlerterStatus.store(alert.id, self.alerter_name, new_alerter_status)
                    alerter_operation_data.store()
                    return alert, status, text
                elif alerter_status == AlerterStatus.Processed:
                    alerter_operation_data_new = AlerterOperationData.from_db(
                        alert.id, self.alerter_name, ALERTERS_KEY_BY_OPERATION[Alerter.process_event.__name__])
                    success = alerter_operation_data_new.success is True
                    if success:
                        self.logger.info("Status changed to closed for an alerted event. Recovering")
                        return self.post_receive(alert, reason=text, force_recovery=True, **kwargs), status, text
                    else:
                        self.logger.info("Status changed to closed for an event that fails alerting. Ignoring")
                        result_data = {"info": {"message": "RECOVERED AN ALERT WITH ERROR IN THE ALERTING"}}
                        new_alerter_status = AlerterStatus.Recovered
                        self._prepare_recovery_special_result(alerter_operation_data, result_data, start_time)
                        AlerterStatus.store(alert.id, self.alerter_name, new_alerter_status)
                        alerter_operation_data.store()
                        return alert, status, text
                elif alerter_status in (AlerterStatus.Processing, AlerterStatus.Repeating, AlerterStatus.Actioning):
                    # Alert will be recovered in the processing task after finish of processing.
                    # If processing finishes ok, or it is a repeating task
                    # the recovery will be launched at the end of the task.
                    # If processing finishes nok or is going to retry,
                    # the recovery will be ignored as alert is supposed to not being notified
                    self.logger.info("Status changed to closed while processing alerting, repeating or action."
                                     " Recovering after finish processing.")
                    alerter_operation_data_pre = AlerterOperationData.last_executing_operation(
                        alert_id=alert.id, alerter=self.alerter_name)
                    new_alerter_status, _, _ = self._prepare_begin_processing(
                        alert, alerter_operation_data, is_recovering=True, is_actioning=False, is_repeating=False,
                        new_event_status=AlerterStatus.Scheduled, reason=text)
                    task_definition = self.get_task_specification(alert, Alerter.process_recovery.__name__)
                    alerter_operation_data_pre.task_chain_info = {
                        AlerterOperationData.FIELD_TASK_CHAIN_INFO_TASK_DEF: task_definition,
                        AlerterOperationData.FIELD_TASK_CHAIN_INFO_TEXT: text
                    }
                    AlerterStatus.store(alert.id, self.alerter_name, new_alerter_status)
                    alerter_operation_data_pre.store()
                    alerter_operation_data.store()
                    return alert, status, text
                elif alerter_status in (AlerterStatus.Recovered, AlerterStatus.Recovering):
                    self.logger.debug("Status changed to closed for an already recovered event. Ignoring.")
                    return None
                else:
                    return None
            else:
                return None
        finally:
            thread_local.alerter_name = None
            thread_local.operation = None

    def take_action(self, alert: Alert, action: str, text: str, **kwargs) -> Any:
        thread_local.alert_id = alert.id
        thread_local.alerter_name = self.alerter_name
        self.global_app_config = kwargs['config']
        timeout = kwargs['timeout']
        try:
            if action not in (Action.CLOSE, Action.EXPIRED) \
                    and alert.status not in (Status.Closed, Status.Expired):
                resolve_action = CC.get_global_configuration(GAttr.CONDITION_RESOLVED_ACTION_NAME)
                # Process operation action
                alerter_status = self.get_alerter_status_for_alert(alert)
                operation_key = action
                thread_local.operation = operation_key
                start_time = datetime.utcnow()
                alerter_operation_data = AlerterOperationData.from_db(alert.id, self.alerter_name, operation_key)
                if alerter_status == AlerterStatus.Scheduled and action == resolve_action:
                    self.logger.info("Action '%s' while waiting to alert. Closing alert", action)
                    return alert, Action.CLOSE, text, timeout
                elif alerter_status in (AlerterStatus.Processed, AlerterStatus.Repeating):
                    # Repeat and action tasks may be launch in parallel
                    alerter_operation_data_new = AlerterOperationData.from_db(
                        alert.id, self.alerter_name, ALERTERS_KEY_BY_OPERATION[Alerter.process_event.__name__])
                    success = alerter_operation_data_new.success is True
                    if success:
                        self.logger.info("Action '%s' for an alerted event. Executing", action)
                        return self.post_receive(alert, reason=text, force_action=action, **kwargs), \
                            action, text, timeout
                    else:
                        self.logger.info("Action '%s' for an event that fails alerting. Ignoring", action)
                        result_data = {
                            "info": {
                                "message": f"ACTION '{action}' FOR AN ALERT WITH ERROR IN THE ALERTING"
                            }
                        }
                        self._prepare_recovery_special_result(alerter_operation_data, result_data, start_time)
                        alerter_operation_data.store()
                        return alert, action, text, timeout
                elif alerter_status in (AlerterStatus.Scheduled, AlerterStatus.Processing):
                    # ACTION will be executed in the processing task after finish of processing.
                    # If processing finishes ok, or it is a repeating task
                    # the recovery will be launched at the end of the task.
                    # If processing finishes nok or is going to retry,
                    # the recovery will be ignored as alert is supposed to not being notified
                    self.logger.info("Action '%s' while processing alerting."
                                     " Executing after finish processing.", action)
                    alerter_operation_data_pre = AlerterOperationData.from_db(
                        alert.id, self.alerter_name, ALERTERS_KEY_BY_OPERATION[Alerter.process_event.__name__])
                    new_alerter_status = AlerterStatus.Actioning
                    task_definition = self.get_task_specification(alert, Alerter.process_action.__name__)
                    alerter_operation_data_pre.task_chain_info = {
                        AlerterOperationData.FIELD_TASK_CHAIN_INFO_TASK_DEF: task_definition,
                        AlerterOperationData.FIELD_TASK_CHAIN_INFO_TEXT: text,
                        AlerterOperationData.FIELD_TASK_CHAIN_INFO_ACTION: action
                    }
                    AlerterStatus.store(alert.id, self.alerter_name, new_alerter_status)
                    alerter_operation_data_pre.store()
                    alerter_operation_data.store()
                    return alert, action, text, timeout
                elif alerter_status in (AlerterStatus.Recovered, AlerterStatus.Recovering):
                    self.logger.debug("Action '%s' for an already recovered event. Ignoring.", action)
                    return None
                else:
                    return None
        finally:
            thread_local.alerter_name = None
            thread_local.operation = None

    def take_note(self, alert: Alert, text: Optional[str], **kwargs) -> Any:
        thread_local.alert_id = alert.id
        thread_local.alerter_name = self.alerter_name
        self.global_app_config = kwargs['config']
        self.logger.debug("Ignoring take_note")
        thread_local.alerter_name = None
        thread_local.operation = None

    def delete(self, alert: Alert, **kwargs) -> bool:
        thread_local.alert_id = alert.id
        thread_local.alerter_name = self.alerter_name
        self.global_app_config = kwargs['config']
        self.logger.debug("Ignoring delete")
        thread_local.alerter_name = None
        thread_local.operation = None
        return True


class IOMSyncAlerterPlugin(IOMAlerterPlugin, ABC):

    def post_receive(self, alert: Alert, **kwargs) -> Optional[Alert]:
        thread_local.alert_id = alert.id
        thread_local.alerter_name = self.alerter_name
        try:
            post_receive_data = self._prepare_post_receive(alert, AlerterStatus.Processing, kwargs)
            if post_receive_data:
                alerter_operation_data, status, begin, delay, operation, reason = post_receive_data
            else:
                return None

            # alert.update_attributes({attribute_name: attr_data})
            alerter_class = self.alerter_data[BGTadC.CLASS]
            response = {}
            try:
                alerter = Alerter.get_alerter_type(alerter_class)(self.alerter_name)
                response = getattr(alerter, operation)(alert, reason)
            except Exception as exc:
                store_traceback = CC.get_contextual_global_config(CC.STORE_TRACEBACK_ON_EXCEPTION,
                                                                  alert, self, operation)[0]
                response = False, Alerter.result_for_exception(exc, include_traceback=store_traceback)
                self.logger.error("Error executing post_receive: %s", exc, exc_info=exc)
            finally:
                now = datetime.utcnow()
                status = AlerterStatus.Recovered if operation == Alerter.process_recovery.__name__ \
                    else AlerterStatus.Processed
                alerter_operation_data = Alerter.prepare_result(alerter_operation_data, response, begin, now)
                self.logger.info("FINISHED IN %.3f sec. RESULT %s -> %s",
                                 (now-begin).total_seconds(),
                                 'SUCCESS' if alerter_operation_data.success else 'FAILURE', response)
            AlerterStatus.store(alert.id, self.alerter_name, status)
            alerter_operation_data.store()
            return alert
        finally:
            thread_local.alerter_name = None
            thread_local.operation = None

    # No need to override status_change.
    # For synchronous plugins, status_change will be executed with alerter status = Processed and
    # parent class implementation will call post_receive sync implementation or do nothing if alerting failed.
    # def status_change(self, alert: Alert, status, text: str, **kwargs) -> Any:
    #     return super().status_change(alert, status, text, **kwargs)
