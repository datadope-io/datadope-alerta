from . import Alert, Alerter, AlerterStatus, AlertTask, result_for_exception, prepare_result, AlerterOperationData

# noinspection PyPackageRequirements
from celery import signature, states
# noinspection PyPackageRequirements
from celery.exceptions import Ignore


class Task(AlertTask):

    def _ignore_recovery_while_processing(self, task_id, alerter_operation_data: AlerterOperationData,
                                          event_retval, recovery_message):
        start_time, end_time, duration = self._get_timing_from_now(task_id=task_id)
        alert_id = alerter_operation_data.alert_id
        alerter_name = alerter_operation_data.alerter
        self._finish_task(alerter_operation_data=alerter_operation_data, status=AlerterStatus.Recovered,
                          retval=event_retval, start_time=start_time, end_time=end_time)
        recovery_retval = True, {"info": {"message": recovery_message}}
        alerter_operation_data_recovery = AlerterOperationData.from_db(alert_id, alerter_name,
                                                                       self.get_recovery_task().get_operation_key())
        alerter_operation_data_recovery = prepare_result(alerter_operation_data=alerter_operation_data_recovery,
                                                         retval=recovery_retval,
                                                         start_time=None,
                                                         end_time=None,
                                                         skipped=True)
        alerter_operation_data_recovery.store()

    @staticmethod
    def get_operation():
        return Alerter.process_event.__name__

    def before_start_operation(self, task_id, alerter_operation_data, current_status, kwargs):
        is_retrying = self.request.retries > 0
        if current_status == AlerterStatus.Recovering:
            self.logger.info("Ignoring task -> Alert recovered before alerting")
            event_retval = not is_retrying, {"info": {"message": "RECOVERED BEFORE ALERTING"}}
            self._ignore_recovery_while_processing(task_id=task_id, alerter_operation_data=alerter_operation_data,
                                                   event_retval=event_retval,
                                                   recovery_message="RECOVERED BEFORE ALERTING OR RETRY")
            self.update_state(state=states.IGNORED)
            raise Ignore()
        elif (current_status == AlerterStatus.Processing and not is_retrying) \
                or current_status not in (AlerterStatus.New, AlerterStatus.Scheduled, AlerterStatus.Processing):
            self.logger.warning("Ignoring task -> Current status is not valid for this task: %s",
                                current_status.value)
            self._time_management.pop(task_id, None)
            self.update_state(state=states.IGNORED)
            raise Ignore()
        return AlerterStatus.Processing

    def on_success_operation(self, alerter_operation_data: AlerterOperationData, current_status, kwargs):
        if current_status == AlerterStatus.Recovering:
            self.logger.info("Alert recovered during processing. Sending recovery from processing task")
            task_data = alerter_operation_data.task_chain_info
            if not task_data:
                self.logger.warning("Recovering task data not found!")
            else:
                alert = Alert.find_by_id(alerter_operation_data.alert_id)
                alerter_operation_data.task_chain_info = None
                reason = task_data.get(AlerterOperationData.FIELD_TASK_CHAIN_INFO_TEXT, alert.text)
                task_def = task_data.get(AlerterOperationData.FIELD_TASK_CHAIN_INFO_TASK_DEF, {})
                kwargs['alert'] = alert
                kwargs['reason'] = reason
                recovery_task = self.get_recovery_task()
                task = signature(recovery_task, args=[], kwargs=kwargs).apply_async(countdown=2.0, **task_def)
                alerter_operation_data_recovery = AlerterOperationData.from_db(
                    alert_id=alerter_operation_data.alert_id,
                    alerter=alerter_operation_data.alerter,
                    operation=recovery_task.get_operation_key())
                alerter_operation_data_recovery.bg_task_id = task.id
                alerter_operation_data_recovery.store()
            return current_status
        return AlerterStatus.Processed

    def on_failure_operation(self, task_id, alerter_operation_data,
                             current_status, retval, kwargs):
        if current_status == AlerterStatus.Recovering:
            # Recovered while processing. Ignoring recovery
            self.logger.info("Alert recovered and processing failed. Ignoring recovery")
            self._ignore_recovery_while_processing(task_id=task_id, alerter_operation_data=alerter_operation_data,
                                                   event_retval=retval,
                                                   recovery_message="RECOVERED BEFORE ALERTING. ALERTING FAILED")
            return None
        return AlerterStatus.Processed

    def on_retry_operation(self, task_id, alerter_operation_data: AlerterOperationData, current_status,
                           exc, einfo, kwargs):
        if current_status == AlerterStatus.Recovering:
            include_traceback = self.request.properties.get('include_traceback', False)
            event_retval = False, result_for_exception(exc, einfo, include_traceback=include_traceback)
            # Recovered while processing. Cancel retries and ignoring recovery
            self.logger.info("Alert recovered before launching a processing retry. Cancelling retry and recovery")
            self._ignore_recovery_while_processing(task_id=task_id, alerter_operation_data=alerter_operation_data,
                                                   event_retval=event_retval,
                                                   recovery_message="RECOVERED BEFORE ALERTING DURING RETRY")
            return False
        return True
