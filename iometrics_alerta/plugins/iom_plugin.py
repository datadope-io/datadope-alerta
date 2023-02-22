import logging
import random
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Optional, Type, Tuple, Union

from alerta.models.alert import Alert
from alerta.models.enums import Status
from alerta.plugins import PluginBase

from iometrics_alerta import DateTime, merge, get_config, thread_local, AlertIdFilter
from iometrics_alerta import AlerterProcessAttributeConstant as AProcC
from iometrics_alerta import BGTaskAlerterDataConstants as BGTadC
# noinspection PyPep8Naming
from iometrics_alerta import ContextualConfiguration as CC
from . import Alerter, AlerterStatus, ATTRIBUTE_KEYS_BY_OPERATION, prepare_result, result_for_exception, \
    has_alerting_succeeded
from .bgtasks import revoke_task, event_task, recovery_task, repeat_task


ALERT_TASK_BY_OPERATION = {
    Alerter.process_event.__name__: event_task,
    Alerter.process_recovery.__name__: recovery_task,
    Alerter.process_repeat.__name__: repeat_task
}


class IOMAlerterPlugin(PluginBase, ABC):

    def __init__(self, name=None):
        name = name or self.__module__.rsplit('.', 1)[0]
        super(IOMAlerterPlugin, self).__init__(name)
        self.logger = logging.getLogger(self.name)
        self.logger.addFilter(AlertIdFilter.get_instance())
        self.__global_app_config = None
        self.__alerter_name = None
        self.__alerter_config = None
        self.__alerter_attribute_name = None

    # noinspection PyShadowingBuiltins
    def get_config(self, key, default=None, type=None, config=None):
        return get_config(key, default, type, self.global_app_config if config is None else config)

    @abstractmethod
    def get_alerter_class(self) -> Type[Alerter]:
        pass

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
    def alerter_attribute_name(self) -> str:
        if self.__alerter_attribute_name is None:
            self.__alerter_attribute_name = AProcC.ATTRIBUTE_FORMATTER.format(alerter_name=self.alerter_name)
        return self.__alerter_attribute_name

    @property
    def alerter_data(self) -> Dict[str, Any]:
        return {
            BGTadC.NAME: self.alerter_name,
            BGTadC.CLASS: Alerter.get_fullname(self.get_alerter_class()),
            BGTadC.PLUGIN: self.name
        }

    def get_alerter_status_for_alert(self, alert):
        return AlerterStatus(alert.attributes.get(self.alerter_attribute_name, {})
                             .get(AProcC.FIELD_STATUS))

    def get_task_specification(self, alert, operation):
        return defaultdict(dict, CC.get_contextual_global_config(CC.TASKS_DEFINITION, alert, self,
                                                                 operation=operation)[0])

    def get_processing_delay(self, alert, operation):
        now = datetime.utcnow()
        create_time = alert.create_time or now
        consumed_time = DateTime.diff_seconds_utc(now, create_time)
        delay = CC.get_contextual_global_config(CC.ACTION_DELAY, alert, self, operation)[0]
        return max(0, delay - consumed_time)

    def _prepare_begin_processing(self, alert, is_recovering, is_repeating, new_event_status: AlerterStatus, reason):
        begin = datetime.now()
        if is_recovering:
            operation = Alerter.process_recovery.__name__
            new_status = AlerterStatus.Recovering.value
            data_field = AProcC.KEY_RECOVERY
            delay = 10.0
        elif is_repeating:
            operation = Alerter.process_repeat.__name__
            new_status = AlerterStatus.Repeating.value
            data_field = AProcC.KEY_REPEAT
            delay = 10.0
        else:
            operation = Alerter.process_event.__name__
            new_status = new_event_status.value
            data_field = AProcC.KEY_NEW_EVENT
            delay = self.get_processing_delay(alert, operation)
        thread_local.operation = ATTRIBUTE_KEYS_BY_OPERATION[operation]
        delay = max(10.0, delay) + random.uniform(-5.0, 5.0)  # +/- 5 secs for the configured delay (min config = 10)
        attr_data = alert.attributes.setdefault(self.alerter_attribute_name, {})
        attr_data[AProcC.FIELD_STATUS] = new_status
        attr_data.setdefault(data_field, {})[AProcC.FIELD_RECEIVED] = DateTime.iso8601_utc(begin)
        reason = reason or CC.get_contextual_global_config(CC.REASON, alert, self, operation)[0]
        attr_data.setdefault(data_field, {})[AProcC.FIELD_REASON] = reason
        return attr_data, self.alerter_attribute_name, attr_data[data_field], begin, operation, delay

    @staticmethod
    def _prepare_result(operation: str,
                        retval: Union[Dict[str, Any], Tuple[bool, Dict[str, Any]]],
                        start_time: datetime = None, end_time: datetime = None,
                        duration: float = None, skipped: bool = None) -> Tuple[bool, Dict[str, Any]]:
        status = AlerterStatus.Recovered if operation == Alerter.process_recovery.__name__ \
            else AlerterStatus.Processed
        data_field = ATTRIBUTE_KEYS_BY_OPERATION[operation]
        return prepare_result(status, data_field, retval, start_time, end_time, duration, skipped)

    def _prepare_recovery_special_result(self, alert, result_data, start_time):
        attr_data = alert.attributes.setdefault(self.alerter_attribute_name, {})
        attr_data[AProcC.FIELD_STATUS] = AlerterStatus.Recovered.value
        recovery_data = attr_data.setdefault(AProcC.KEY_RECOVERY, {})
        recovery_data[AProcC.FIELD_RECEIVED] = DateTime.iso8601_utc(start_time)
        recovery_data[AProcC.FIELD_SUCCESS] = True
        recovery_data[AProcC.FIELD_RESPONSE] = result_data
        recovery_data[AProcC.FIELD_SKIPPED] = True

    def _get_last_repeat_time(self, alert):
        attr_data = alert.attributes.setdefault(self.alerter_attribute_name, {})
        last = attr_data.get(AProcC.KEY_REPEAT, {}).get(AProcC.FIELD_RECEIVED) \
            or attr_data.get(AProcC.KEY_NEW_EVENT, {}).get(AProcC.FIELD_RECEIVED)
        if last:
            return DateTime.parse(last)
        else:
            return DateTime.make_aware_utc(datetime.now())

    def _prepare_post_receive(self, alert, new_event_status: AlerterStatus, kwargs):
        thread_local.operation = ATTRIBUTE_KEYS_BY_OPERATION[Alerter.process_event.__name__]
        self.global_app_config = kwargs['config']
        force_recovery = kwargs.get('force_recovery', False)
        force_repeat = kwargs.get('force_repeat', False)
        recovering = force_recovery or alert.status == Status.Closed
        if recovering:
            thread_local.operation = ATTRIBUTE_KEYS_BY_OPERATION[Alerter.process_recovery.__name__]
        alerter_status = self.get_alerter_status_for_alert(alert)
        repeating = not recovering and alerter_status == AlerterStatus.Processed
        if repeating:
            thread_local.operation = ATTRIBUTE_KEYS_BY_OPERATION[Alerter.process_repeat.__name__]
        if repeating and not force_repeat:
            # Is repeating but check if the interval is good
            success = has_alerting_succeeded(alert, self.alerter_attribute_name)
            if success:
                repeating_interval = CC.get_contextual_global_config(CC.REPEAT_MIN_INTERVAL, alert, self)[0]
                if repeating_interval:
                    last_repetition = self._get_last_repeat_time(alert)
                    now = DateTime.make_aware_utc(datetime.now())
                    repeating = (now - last_repetition).total_seconds() > repeating_interval
                    if not repeating:
                        self.logger.debug("Not repeating. Interval among repetitions not reached.")
                else:
                    repeating = False
                    self.logger.debug("Not repeating. Repetition is deactivated.")
            else:
                self.logger.debug("Not repeating a failed alerting")
                repeating = False
        if alert.repeat and not recovering and not repeating and alerter_status != AlerterStatus.New:
            self.logger.info("Ignoring repetition")
            return None
        self.logger.debug("Entering post_receive method")
        reason = kwargs.get('reason') or alert.text
        attr_data, attribute_name, event_data, begin, operation, delay = self._prepare_begin_processing(
            alert, is_recovering=recovering, is_repeating=repeating, new_event_status=new_event_status, reason=reason)
        return attr_data, begin, delay, event_data, operation, reason, attribute_name

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
                attr_data, begin, delay, event_data, operation, reason, _ = post_receive_data
                delay = 2 if kwargs.get('ignore_delay', False) else delay
            else:
                return None

            store_traceback = CC.get_contextual_global_config(CC.STORE_TRACEBACK_ON_EXCEPTION,
                                                              alert, self, operation)[0]
            try:
                task_specification = self.get_task_specification(alert, operation)
                task_instance = ALERT_TASK_BY_OPERATION[operation]
                task = task_instance.apply_async(
                    kwargs=dict(alerter_data=self.alerter_data, alert=alert, reason=reason),
                    countdown=round(delay), **task_specification, include_traceback=store_traceback)
                self.logger.info("Scheduled task '%s' to run in %.0f seconds in queue '%s'",
                                 task.id, delay, task_specification.get('queue', '<default>'))
                event_data[AProcC.FIELD_BG_TASK_ID] = task.id
                # Attributes modification will be stored automatically at return
            except Exception as e:
                self.logger.error("Error executing post_receive: %s", e, exc_info=e)
                now = datetime.now()
                retval = False, result_for_exception(e, include_traceback=store_traceback)
                success, new_attr_data = IOMAlerterPlugin._prepare_result(operation=operation, retval=retval,
                                                                          start_time=begin, end_time=now,
                                                                          duration=(now-begin).total_seconds())
                merge(attr_data, new_attr_data)
                # Attributes modification will be stored automatically at return
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
            if status == Status.Closed:
                ignore_recovery, level = CC.get_contextual_global_config(CC.IGNORE_RECOVERY, alert, self)
                if alerter_status == AlerterStatus.Scheduled:
                    bgtask_id = alert.attributes.get(self.alerter_attribute_name, {})\
                        .get(AProcC.KEY_NEW_EVENT, {}).get(AProcC.FIELD_BG_TASK_ID)
                    if bgtask_id:
                        revoke_task(bgtask_id)
                        self.logger.info("Status changed to closed while waiting to alert. Revoking alert task %s.",
                                         bgtask_id)
                    else:
                        self.logger.warning("BGTASK ID NOT FOUND")
                    start_time = datetime.now()
                    result_data = {"info": {"message": "RECOVERED BEFORE ALERTING"}}
                    self._prepare_recovery_special_result(alert, result_data, start_time)
                    event_data = alert.attributes[self.alerter_attribute_name].setdefault(AProcC.KEY_NEW_EVENT, {})
                    event_data[AProcC.FIELD_SUCCESS] = True
                    event_data[AProcC.FIELD_RESPONSE] = result_data
                    event_data[AProcC.FIELD_SKIPPED] = True
                    # Attributes modification will be stored automatically at return
                    return alert, status, text
                elif ignore_recovery:
                    self.logger.info("Ignoring recovery configured with context '%s'", level.value)
                    start_time = datetime.now()
                    result_data = {"info": {"message": "IGNORED RECOVERY"}}
                    self._prepare_recovery_special_result(alert, result_data, start_time)
                    # Attributes modification will be stored automatically at return
                    return alert, status, text
                elif alerter_status == AlerterStatus.Processed:
                    success = has_alerting_succeeded(alert, self.alerter_attribute_name)
                    if success:
                        self.logger.info("Status changed to closed for an alerted event. Recovering")
                        return self.post_receive(alert, reason=text, force_recovery=True, **kwargs), status, text
                    else:
                        self.logger.info("Status changed to closed for an event that fails alerting. Ignoring")
                        start_time = datetime.now()
                        result_data = {"info": {"message": "RECOVERED AND ALERT WITH ERROR IN THE ALERTING"}}
                        self._prepare_recovery_special_result(alert, result_data, start_time)
                        # Attributes modification will be stored automatically at return
                        return alert, status, text
                elif alerter_status in (AlerterStatus.Processing, AlerterStatus.Repeating):
                    # Alert will be recovered in the processing task after finish of processing.
                    # If processing finishes ok, or it is a repeating task
                    # the recovery will be launched at the end of the task.
                    # If processing finishes nok or is going to retry,
                    # the recovery will be ignored as alert is supposed to not being notified
                    self.logger.info("Status changed to closed while processing alerting."
                                     " Recovering after finish processing.")
                    attr_data, _, _, _, _, _ = self._prepare_begin_processing(
                        alert, is_recovering=True, is_repeating=False, new_event_status=AlerterStatus.Scheduled,
                        reason=text)
                    task_definition = self.get_task_specification(alert, Alerter.process_recovery.__name__)
                    attr_data[AProcC.FIELD_TEMP_RECOVERY_DATA] = {
                        AProcC.FIELD_TEMP_RECOVERY_DATA_TASK_DEF: task_definition,
                        AProcC.FIELD_TEMP_RECOVERY_DATA_TEXT: text
                    }
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
        self.logger.debug("Ignoring take_action")
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
                attr_data, begin, delay, event_data, operation, reason, attribute_name = post_receive_data
            else:
                return None
            alert.update_attributes({attribute_name: attr_data})
            alerter_class = self.alerter_data[BGTadC.CLASS]
            response = {}
            try:
                alerter = Alerter.get_alerter_type(alerter_class)(self.alerter_name)
                response = getattr(alerter, operation)(alert, reason)
            except Exception as exc:
                store_traceback = CC.get_contextual_global_config(CC.STORE_TRACEBACK_ON_EXCEPTION,
                                                                  alert, self, operation)[0]
                response = False, result_for_exception(exc, include_traceback=store_traceback)
                self.logger.error("Error executing post_receive: %s", exc, exc_info=exc)
            finally:
                now = datetime.now()
                duration = (now - begin).total_seconds()
                success, new_attr_data = IOMAlerterPlugin._prepare_result(operation=operation, retval=response,
                                                                          start_time=begin, end_time=now,
                                                                          duration=duration)
                self.logger.info("FINISHED IN %.3f sec. RESULT %s -> %s",
                                 duration, 'SUCCESS' if success else 'FAILURE', response)
                merge(attr_data, new_attr_data)
                # Attributes modification will be stored automatically at return
            return alert
        finally:
            thread_local.alerter_name = None
            thread_local.operation = None

    # No need to override status_change.
    # For synchronous plugins, status_change will be executed with alerter status = Processed and
    # parent class implementation will call post_receive sync implementation or do nothing if alerting failed.
    # def status_change(self, alert: Alert, status, text: str, **kwargs) -> Any:
    #     return super().status_change(alert, status, text, **kwargs)
