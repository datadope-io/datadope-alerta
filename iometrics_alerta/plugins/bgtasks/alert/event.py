from . import Alerter, AlerterStatus, AlertTask, AProcC, result_for_exception, prepare_result

# noinspection PyPackageRequirements
from celery import signature, states
# noinspection PyPackageRequirements
from celery.exceptions import Ignore


class Task(AlertTask):

    def _ignore_recovery_while_processing(self, task_id, alert, alerter_name, event_retval, recovery_message):
        start_time, end_time, duration = self._get_timing_from_now(task_id=task_id)
        self._finish_task(alert=alert, alerter_name=alerter_name, status=AlerterStatus.Processed, retval=event_retval,
                          start_time=start_time, end_time=end_time, duration=duration, update_db=False)
        recovery_retval = True, {"info": {"message": recovery_message}}
        _, attribute_data = prepare_result(status=AlerterStatus.Recovered,
                                           data_field=self.get_recovery_task().get_data_field(),
                                           retval=recovery_retval,
                                           start_time=None,
                                           end_time=None,
                                           duration=None,
                                           skipped=True)
        self._update_alerter_attribute(alert, alerter_name, attribute_data, remove_temp_recovery_data_attr=True)

    @staticmethod
    def get_operation():
        return Alerter.process_event.__name__

    def before_start_operation(self, task_id, alert, alerter_name, alerter_attr_data, current_status, kwargs):
        is_retrying = self.request.retries > 0
        if current_status == AlerterStatus.Recovering:
            self.logger.info("Ignoring task %s:%s' for alert '%s' -> Alert recovered before alerting",
                             alerter_name, self.get_operation(), alert.id)
            event_retval = not is_retrying, {"info": {"message": "RECOVERED BEFORE ALERTING"}}
            self._ignore_recovery_while_processing(task_id=task_id, alert=alert, alerter_name=alerter_name,
                                                   event_retval=event_retval,
                                                   recovery_message="RECOVERED BEFORE ALERTING OR RETRY")
            self.update_state(state=states.IGNORED)
            raise Ignore()
        elif (current_status == AlerterStatus.Processing and not is_retrying) \
                or current_status not in (AlerterStatus.New, AlerterStatus.Scheduled, AlerterStatus.Processing):
            self.logger.warning("Ignoring task %s:%s' for alert '%s' -> Current status is not valid for this task: %s",
                                alerter_name, self.get_operation(), alert.id, current_status.value)
            self._time_management.pop(task_id, None)
            self.update_state(state=states.IGNORED)
            raise Ignore()
        return AlerterStatus.Processing

    def on_success_operation(self, alert, alerter_attr_data, current_status, kwargs):
        if current_status == AlerterStatus.Recovering:
            self.logger.info("Alert %s recovered during processing. Sending recovery from processing task",
                             alert.id)
            task_data = alerter_attr_data.pop(AProcC.FIELD_TEMP_RECOVERY_DATA, {})
            reason = task_data.get(AProcC.FIELD_TEMP_RECOVERY_DATA_TEXT, alert.text)
            task_def = task_data.get(AProcC.FIELD_TEMP_RECOVERY_DATA_TASK_DEF, {})
            kwargs['alert'] = alert
            kwargs['reason'] = reason
            recovery_task = self.get_recovery_task()
            task = signature(recovery_task, args=[], kwargs=kwargs).apply_async(countdown=2.0, **task_def)
            alerter_attr_data.setdefault(recovery_task.get_data_field(), {})[AProcC.FIELD_BG_TASK_ID] = task.id
            return current_status
        return AlerterStatus.Processed

    def on_failure_operation(self, task_id, alert, alerter_name, alerter_attr_data,
                             current_status, retval, kwargs):
        if current_status == AlerterStatus.Recovering:
            # Recovered while processing. Ignoring recovery
            self.logger.info("Alert %s recovered and processing failed. Ignoring recovery", alert.id)
            self._ignore_recovery_while_processing(task_id=task_id, alert=alert, alerter_name=alerter_name,
                                                   event_retval=retval,
                                                   recovery_message="RECOVERED BEFORE ALERTING. ALERTING FAILED")
            return None
        return AlerterStatus.Processed

    def on_retry_operation(self, task_id, alert, alerter_name, alerter_attr_data, current_status, exc, einfo, kwargs):
        if current_status == AlerterStatus.Recovering:
            include_traceback = self.request.properties.get('include_traceback', False)
            event_retval = False, result_for_exception(exc, einfo, include_traceback=include_traceback)
            # Recovered while processing. Cancel retries and ignoring recovery
            self.logger.info("Alert %s recovered before launching a processing retry. Cancelling retry and recovery",
                             alert.id)
            self._ignore_recovery_while_processing(task_id=task_id, alert=alert, alerter_name=alerter_name,
                                                   event_retval=event_retval,
                                                   recovery_message="RECOVERED BEFORE ALERTING DURING RETRY")
            return False
        return True
