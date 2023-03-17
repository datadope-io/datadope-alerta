from . import Alert, Alerter, AlerterStatus, AlertTask, AlerterOperationData

# noinspection PyPackageRequirements
from celery import states, signature
# noinspection PyPackageRequirements
from celery.exceptions import Ignore


class Task(AlertTask):

    def _schedule_recovery_task(self, alert, alerter_operation_data: AlerterOperationData, kwargs):
        task_data = alerter_operation_data.task_chain_info
        if not task_data:
            self.logger.warning("Recovering task data not found!")
        else:
            alerter_operation_data.task_chain_info = None
            reason = task_data.get(AlerterOperationData.FIELD_TASK_CHAIN_INFO_TEXT, "")
            task_def = task_data.get(AlerterOperationData.FIELD_TASK_CHAIN_INFO_TASK_DEF, {})
            kwargs['alert'] = alert
            kwargs['reason'] = reason
            recovery_task = self.get_recovery_task()
            task = signature(recovery_task, args=[], kwargs=kwargs).apply_async(countdown=2.0, **task_def)
            alerter_operation_data_recovery = AlerterOperationData.from_db(alerter_operation_data.alert_id,
                                                                           alerter_operation_data.alerter,
                                                                           recovery_task.get_operation_key())
            alerter_operation_data_recovery.bg_task_id = task.id
            alerter_operation_data_recovery.store()

    @staticmethod
    def get_operation():
        return Alerter.process_action.__name__

    def before_start_operation(self, task_id, alerter_operation_data, current_status, kwargs):
        is_retrying = self.request.retries > 0
        if current_status == AlerterStatus.Recovering:
            self.logger.info("Ignoring action task -> Alert recovered before action. Recovering")
            alert = Alert.find_by_id(alerter_operation_data.alert_id)
            self._time_management.pop(task_id, None)
            start_time, end_time, duration = self._get_timing_from_now(task_id=task_id)
            event_retval = not is_retrying, {"info": {"message": "RECOVERED BEFORE ACTION"}}
            self._schedule_recovery_task(alert, alerter_operation_data, kwargs)
            self._finish_task(alerter_operation_data=alerter_operation_data, status=current_status,
                              retval=event_retval, start_time=start_time, end_time=end_time)
            self.update_state(state=states.IGNORED)
            raise Ignore()
        elif current_status not in (AlerterStatus.Actioning, AlerterStatus.Repeating):
            self.logger.warning("Ignoring action task -> Current status is not valid for this task: %s",
                                current_status.value)
            self._time_management.pop(task_id, None)
            self.update_state(state=states.IGNORED)
            raise Ignore()
        return AlerterStatus.Actioning

    def on_success_operation(self, alerter_operation_data: AlerterOperationData, current_status, kwargs):
        if current_status == AlerterStatus.Recovering:
            alert = Alert.find_by_id(alerter_operation_data.alert_id)
            self.logger.info("Alert recovered during action. Sending recovery from repeat task")
            self._schedule_recovery_task(alert, alerter_operation_data, kwargs)
            return AlerterStatus.Recovering
        return AlerterStatus.Processed

    def on_failure_operation(self, task_id, alerter_operation_data: AlerterOperationData,
                             current_status, retval, kwargs):
        if current_status == AlerterStatus.Recovering:
            # Recovered while processing. Ignoring recovery
            alert = Alert.find_by_id(alerter_operation_data.alert_id)
            self.logger.info("Alert recovered and action failed. Sending recovery from repeat")
            self._schedule_recovery_task(alert, alerter_operation_data, kwargs)
            return AlerterStatus.Recovering
        return AlerterStatus.Processed

    def on_retry_operation(self, task_id, alerter_operation_data, current_status, exc, einfo, kwargs):
        if current_status == AlerterStatus.Recovering:
            alert = Alert.find_by_id(alerter_operation_data.alert_id)
            self.logger.info("Alert recovered before launching an action retry. "
                             "Cancelling retry and sending recovery")
            include_traceback = self.request.properties.get('include_traceback', False)
            retval = False, Alerter.result_for_exception(exc, einfo, include_traceback=include_traceback)
            start_time, end_time, duration = self._get_timing_from_now(task_id)
            self._time_management.pop(task_id, None)
            self._schedule_recovery_task(alert, alerter_operation_data, kwargs)
            self._finish_task(alerter_operation_data=alerter_operation_data, status=AlerterStatus.Recovering,
                              retval=retval, start_time=start_time, end_time=end_time)
            return False
        return True
