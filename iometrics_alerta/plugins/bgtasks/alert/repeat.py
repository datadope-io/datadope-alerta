from . import Alerter, AlerterStatus, AlertTask, AProcC, result_for_exception

# noinspection PyPackageRequirements
from celery import states, signature
# noinspection PyPackageRequirements
from celery.exceptions import Ignore


class Task(AlertTask):

    @classmethod
    def _schedule_recovery_task(cls, alert, alerter_attr_data, kwargs):
        task_data = alerter_attr_data.pop(AProcC.FIELD_TEMP_RECOVERY_DATA, {})
        reason = task_data.get(AProcC.FIELD_TEMP_RECOVERY_DATA_TEXT, alert.text)
        task_def = task_data.get(AProcC.FIELD_TEMP_RECOVERY_DATA_TASK_DEF, {})
        kwargs['alert'] = alert
        kwargs['reason'] = reason
        recovery_task = cls.get_recovery_task()
        task = signature(recovery_task, args=[], kwargs=kwargs).apply_async(countdown=2.0, **task_def)
        alerter_attr_data.setdefault(recovery_task.get_data_field(), {})[AProcC.FIELD_BG_TASK_ID] = task.id

    @staticmethod
    def get_operation():
        return Alerter.process_repeat.__name__

    def before_start_operation(self, task_id, alert, alerter_name, alerter_attr_data, current_status, kwargs):
        if current_status == AlerterStatus.Recovering:
            self.logger.info("Ignoring repeat task -> Alert recovered before repeating. Recovering")
            self._time_management.pop(task_id, None)
            self._schedule_recovery_task(alert, alerter_attr_data, kwargs)
            self.update_state(state=states.IGNORED)
            raise Ignore()
        elif current_status != AlerterStatus.Repeating:
            self.logger.warning("Ignoring repeat task -> Current status is not valid for this task: %s",
                                current_status.value)
            self._time_management.pop(task_id, None)
            self.update_state(state=states.IGNORED)
            raise Ignore()
        if self.request.retries == 0:
            result_dict = alerter_attr_data.setdefault(self.get_data_field(), {})
            result_dict.update({
                AProcC.FIELD_SUCCESS: None,
                AProcC.FIELD_END: None,
                AProcC.FIELD_RESPONSE: None,
                AProcC.FIELD_ELAPSED: None,
                AProcC.FIELD_REPETITIONS: result_dict.get(AProcC.FIELD_REPETITIONS, 0) + 1
            })
        return AlerterStatus.Repeating

    def on_success_operation(self, alert, alerter_attr_data, current_status, kwargs):
        if current_status == AlerterStatus.Recovering:
            self.logger.info("Alert %s recovered during repeating. Sending recovery from repeat task",
                             alert.id)
            self._schedule_recovery_task(alert, alerter_attr_data, kwargs)
            return AlerterStatus.Recovering
        return AlerterStatus.Processed

    def on_failure_operation(self, task_id, alert, alerter_name, alerter_attr_data, current_status, retval, kwargs):
        if current_status == AlerterStatus.Recovering:
            # Recovered while processing. Ignoring recovery
            self.logger.info("Alert %s recovered and repeating failed. Sending recovery from repeat", alert.id)
            self._schedule_recovery_task(alert, alerter_attr_data, kwargs)
            return AlerterStatus.Recovering
        return AlerterStatus.Processed

    def on_retry_operation(self, task_id, alert, alerter_name, alerter_attr_data, current_status, exc, einfo, kwargs):
        if current_status == AlerterStatus.Recovering:
            self.logger.info("Alert %s recovered before launching a repeat retry. "
                             "Cancelling retry and sending recovery",
                             alert.id)
            include_traceback = self.request.properties.get('include_traceback', False)
            retval = False, result_for_exception(exc, einfo, include_traceback=include_traceback)
            start_time, end_time, duration = self._get_timing_from_now(task_id)
            self._finish_task(alert=alert, alerter_name=alerter_name, status=AlerterStatus.Recovering, retval=retval,
                              start_time=start_time, end_time=end_time, duration=duration)
            self._time_management.pop(task_id, None)
            self._schedule_recovery_task(alert, alerter_attr_data, kwargs)
            return False
        return True
