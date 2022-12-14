import json
import logging
import random
import traceback
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime
from json import JSONDecodeError
from typing import Any, Dict, Optional, Type, Tuple, Union

from alerta.models.alert import Alert
from alerta.models.enums import Status
from alerta.plugins import PluginBase

from iometrics_alerta import DateTime, merge, ALERTER_SPECIFIC_CONFIG_KEY_SUFFIX
from iometrics_alerta import AlerterProcessAttributeConstant as AProcC
from iometrics_alerta import BGTaskAlerterDataConstants as BGTadC
# noinspection PyPep8Naming
from iometrics_alerta import ContextualConfiguration as CC
from iometrics_alerta.plugins import Alerter, AlerterStatus
from iometrics_alerta.plugins.bgtasks import run_in_bg, revoke_task


class IOMAlerterPlugin(PluginBase, ABC):

    def __init__(self, name=None):
        name = name or self.__module__.rsplit('.', 1)[0]
        super(IOMAlerterPlugin, self).__init__(name)
        self.logger = logging.getLogger(self.name)
        self.__global_app_config = None
        self.__alerter_name = None
        self.__alerter_config = None
        self.__alerter_attribute_name = None

    @abstractmethod
    def get_alerter_class(self) -> Type[Alerter]:
        pass

    @abstractmethod
    def get_alerter_default_configuration(self) -> dict:
        """
        Provides alerter default configuration overridable with an environment value.

        :return:
        """
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
    def alerter_config(self):
        if self.__alerter_config is None:
            self.__alerter_config = self.read_alerter_config()
        return self.__alerter_config

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
            BGTadC.CONFIG: self.alerter_config,
            BGTadC.PLUGIN: self.name
        }

    def read_alerter_config(self) -> Dict[str, Any]:
        """
        Reads alerter config using global app configuration. First get default configuration
        from alerter and merges it with configuration from environment or config file.

        Configuration key retrieved will be form as'<ALERTER_NAME>_CONFIG'
        (using uppercase form of alerter_name property).

        Override to implement a different mechanism to get the config for the alerter.

        :return: alerter configuration
        """
        default = self.get_alerter_default_configuration() or {}
        config_key = f"{self.alerter_name.upper()}{ALERTER_SPECIFIC_CONFIG_KEY_SUFFIX}"
        config = self.get_config(config_key, default={}, config=self.global_app_config)
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except JSONDecodeError:
                self.logger.error("Wrong configuration for alerter '%s': '%s'",
                                  self.alerter_name, config)
                config = {}
        return merge(default, config)

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

    def _prepare_begin_processing(self, alert, is_recovering):
        begin = datetime.now()
        if is_recovering:
            operation = Alerter.process_recovery.__name__
            new_status = AlerterStatus.Recovering.value
            data_field = AProcC.KEY_RECOVERY
            delay = 10.0
        else:
            operation = Alerter.process_event.__name__
            new_status = AlerterStatus.Scheduled.value
            data_field = AProcC.KEY_NEW_EVENT
            delay = self.get_processing_delay(alert, operation)
        delay = max(10.0, delay) + random.uniform(-5.0, 5.0)  # +/- 5 secs for the configured delay (min config = 10)
        attr_data = alert.attributes.setdefault(self.alerter_attribute_name, {})
        attr_data[AProcC.FIELD_STATUS] = new_status
        attr_data.setdefault(data_field, {})[AProcC.FIELD_RECEIVED] = DateTime.iso8601_utc(begin)
        return attr_data, self.alerter_attribute_name, attr_data[data_field], begin, operation, delay

    @staticmethod
    def prepare_result(operation: str,
                       retval: Union[Dict[str, Any], Tuple[bool, Dict[str, Any]]],
                       start_time: datetime = None, end_time: datetime = None, duration: float = None,
                       new_status=None) -> Tuple[bool, Dict[str, Any]]:
        if operation == Alerter.process_event.__name__:
            new_status = new_status or AlerterStatus.Processed
            data_field = AProcC.KEY_NEW_EVENT
        else:
            new_status = new_status or AlerterStatus.Recovered
            data_field = AProcC.KEY_RECOVERY
        if isinstance(retval, tuple):
            result = {
                AProcC.FIELD_SUCCESS: retval[0],
                AProcC.FIELD_RESPONSE: retval[1]
            }
        else:
            result = {
                AProcC.FIELD_SUCCESS: True,
                AProcC.FIELD_RESPONSE: retval
            }
        if start_time:
            result[AProcC.FIELD_START] = DateTime.iso8601_utc(start_time)
        if end_time:
            result[AProcC.FIELD_END] = DateTime.iso8601_utc(end_time)
        if duration is None and start_time is not None and end_time is not None:
            duration = (end_time - start_time).total_seconds()
        if duration is not None:
            result[AProcC.FIELD_ELAPSED] = duration
        return result[AProcC.FIELD_SUCCESS], {
                AProcC.FIELD_STATUS: new_status,
                data_field: result
        }

    @staticmethod
    def result_for_exception(exc, einfo=None):
        if exc is None and einfo is None:
            try:
                raise Exception('Failure without exception')
            except Exception as e:
                exc = e
        return {
            'reason': 'exception',
            'info': {
                'message': str(einfo.exception if einfo else exc),
                'type': (einfo.type if einfo else type(exc)).__name__,
                'traceback': einfo.traceback if einfo else ''.join(traceback.format_exception(type(exc),
                                                                                              exc,
                                                                                              exc.__traceback__))
            }
        }

    def _prepare_recovery_special_result(self, alert, result_data, start_time):
        attr_data = alert.attributes.setdefault(self.alerter_attribute_name, {})
        attr_data[AProcC.FIELD_STATUS] = AlerterStatus.Recovered.value
        recovery_data = attr_data.setdefault(AProcC.KEY_RECOVERY, {})
        recovery_data[AProcC.FIELD_RECEIVED] = DateTime.iso8601_utc(start_time)
        recovery_data[AProcC.FIELD_SUCCESS] = True
        recovery_data[AProcC.FIELD_RESPONSE] = result_data

    #
    # PluginBase ABSTRACT METHODS IMPLEMENTATION
    #
    def pre_receive(self, alert: Alert, **kwargs) -> Alert:
        self.global_app_config = kwargs['config']
        self.logger.debug("Ignoring pre_receive")
        return alert

    def post_receive(self, alert: Alert, **kwargs) -> Optional[Alert]:
        self.global_app_config = kwargs['config']
        force_recovery = kwargs.get('force_recovery', False)
        recovering = force_recovery or alert.status == Status.Closed
        alerter_status = self.get_alerter_status_for_alert(alert)
        if alert.repeat and not recovering and alerter_status != AlerterStatus.New:
            self.logger.info("%s: Ignoring repetition of alert %s", self.name, alert.id)
            return None
        self.logger.debug("Entering post_receive method for alert '%s'", alert.id)
        reason = kwargs.get('reason') or alert.text
        attr_data, attribute_name, event_data, begin, operation, delay = self._prepare_begin_processing(
            alert, is_recovering=recovering)
        try:
            task_specification = self.get_task_specification(alert, operation)
            task = run_in_bg.apply_async(
                kwargs=dict(alerter_data=self.alerter_data, alert=alert, operation=operation, reason=reason),
                countdown=round(delay), **task_specification)
            self.logger.info("Scheduled task '%s' to run in %.0f seconds in queue '%s'",
                             task.id, delay, task_specification.get('queue', '<default>'))
            event_data[AProcC.FIELD_BG_TASK_ID] = task.id
            # Attributes modification will be stored automatically at return
        except Exception as e:
            self.logger.error("Error executing post_receive for plugin '%s': %s", self.name, e, exc_info=e)
            now = datetime.now()
            retval = False, self.result_for_exception(e)
            success, new_attr_data = IOMAlerterPlugin.prepare_result(operation=operation, retval=retval,
                                                                     start_time=begin, end_time=now,
                                                                     duration=(now-begin).total_seconds())
            merge(attr_data, new_attr_data)
            # Attributes modification will be stored automatically at return
        return alert

    def status_change(self, alert: Alert, status, text: str, **kwargs) -> Any:
        self.global_app_config = kwargs['config']
        current_status = Status(alert.status)
        if status == current_status:
            return None
        alerter_status = self.get_alerter_status_for_alert(alert)
        if status == Status.Closed:
            ignore_recovery, level = CC.get_contextual_global_config(CC.IGNORE_RECOVERY, alert, self)
            if alerter_status == AlerterStatus.Scheduled:
                self.logger.debug("Status changed to closed while waiting to alert. Revoking alert task.")
                bgtask_id = alert.attributes.get(self.alerter_attribute_name, {})\
                    .get(AProcC.KEY_NEW_EVENT, {}).get(AProcC.FIELD_BG_TASK_ID)
                if bgtask_id:
                    revoke_task(bgtask_id)
                    self.logger.info("Status changed to closed while waiting to alert. Revoking alert task %s.",
                                     bgtask_id)
                else:
                    self.logger.warning("BGTASK ID NOT FOUND FOR ALERTER: %s, ALERT: %s",
                                        self.alerter_name, alert.id)
                start_time = datetime.now()
                result_data = {"info": {"message": "RECOVERED BEFORE ALERTING"}}
                self._prepare_recovery_special_result(alert, result_data, start_time)
                event_data = alert.attributes[self.alerter_attribute_name].setdefault(AProcC.KEY_NEW_EVENT, {})
                event_data[AProcC.FIELD_SUCCESS] = True
                event_data[AProcC.FIELD_RESPONSE] = result_data
                # Attributes modification will be stored automatically at return
                return alert, status, text
            elif ignore_recovery:
                self.logger.info("Ignoring recovery configured with context '%s', for alert '%s'",
                                 level.value, alert.id)
                start_time = datetime.now()
                result_data = {"info": {"message": "IGNORED RECOVERY"}}
                self._prepare_recovery_special_result(alert, result_data, start_time)
                # Attributes modification will be stored automatically at return
                return alert, status, text
            elif alerter_status == AlerterStatus.Processed:
                success = alert.attributes.get(self.alerter_attribute_name, {}) \
                    .get(AProcC.KEY_NEW_EVENT, {}).get(AProcC.FIELD_SUCCESS, False)
                if success:
                    self.logger.debug("Status changed to closed for an alerted event. Recovering")
                    return self.post_receive(alert, reason=text, force_recovery=True, **kwargs), status, text
                else:
                    self.logger.debug("Status changed to closed for an event that fails alerting. Ignoring")
                    start_time = datetime.now()
                    result_data = {"info": {"message": "RECOVERED AND ALERT WITH ERROR IN THE ALERTING"}}
                    self._prepare_recovery_special_result(alert, result_data, start_time)
                    # Attributes modification will be stored automatically at return
                    return alert, status, text
            elif alerter_status == AlerterStatus.Processing:
                # Alert will be recovered in the processing task after finish of processing.
                # If processing finishes ok, the recover will be launched at the end of the task.
                # If processing finishes nok or is going to retry,
                # the recovery will be ignored as alert is supposed to not being notified
                self.logger.debug("Status changed to closed while processing alerting."
                                  " Recovering after finish processing.")
                attr_data, _, _, _, _, _ = self._prepare_begin_processing(
                    alert, is_recovering=True)
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

    def take_action(self, alert: Alert, action: str, text: str, **kwargs) -> Any:
        self.global_app_config = kwargs['config']
        self.logger.debug("Ignoring take_action")

    def take_note(self, alert: Alert, text: Optional[str], **kwargs) -> Any:
        self.global_app_config = kwargs['config']
        self.logger.debug("Ignoring take_note")

    def delete(self, alert: Alert, **kwargs) -> bool:
        self.global_app_config = kwargs['config']
        self.logger.debug("Ignoring delete")
        return True


class IOMSyncAlerterPlugin(IOMAlerterPlugin, ABC):

    def post_receive(self, alert: Alert, **kwargs) -> Optional[Alert]:
        self.global_app_config = kwargs['config']
        force_recovery = kwargs.get('force_recovery', False)
        recovering = force_recovery or alert.status == Status.Closed
        alerter_status = self.get_alerter_status_for_alert(alert)
        if alert.repeat and not recovering and alerter_status != AlerterStatus.New:
            self.logger.info("%s: Ignoring repetition of alert %s", self.name, alert.id)
            return None
        self.logger.debug("Entering post_receive method for alert '%s'", alert.id)
        reason = kwargs.get('reason') or alert.text
        attr_data, attribute_name, _, begin, operation, _ = self._prepare_begin_processing(
            alert, is_recovering=recovering)
        if not recovering:
            attr_data[AProcC.FIELD_STATUS] = AlerterStatus.Processing.value
        alert.update_attributes({attribute_name: attr_data})
        alerter_class = self.alerter_data[BGTadC.CLASS]
        response = {}
        try:
            alerter = Alerter.get_alerter_type(alerter_class)(self.alerter_data[BGTadC.CONFIG])
            response = getattr(alerter, operation)(alert, reason)
        except Exception as exc:
            response = False, self.result_for_exception(exc)
            self.logger.error("Error executing post_receive for plugin '%s': %s", self.name, exc, exc_info=exc)
        finally:
            now = datetime.now()
            duration = (now - begin).total_seconds()
            success, new_attr_data = IOMAlerterPlugin.prepare_result(operation=operation, retval=response,
                                                                     start_time=begin, end_time=now, duration=duration)
            self.logger.info("PROCESS FINISHED IN %.3f sec. RESULT %s FOR ALERT '%s' IN %s:%s -> %s",
                             duration, 'SUCCESS' if success else 'FAILURE', alert.id,
                             self.alerter_name, operation, response)
            merge(attr_data, new_attr_data)
            # Attributes modification will be stored automatically at return
        return alert
