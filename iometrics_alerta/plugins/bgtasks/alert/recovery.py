from . import Alerter, AlerterStatus, AlertTask

# noinspection PyPackageRequirements
from celery import states
# noinspection PyPackageRequirements
from celery.exceptions import Ignore


class Task(AlertTask):

    @staticmethod
    def get_operation():
        return Alerter.process_recovery.__name__

    def before_start_operation(self, task_id, alerter_operation_data, current_status, kwargs):
        if current_status != AlerterStatus.Recovering:
            self.logger.warning("Ignoring task -> Current status is not valid for this task: %s", current_status.value)
            self._time_management.pop(task_id, None)
            self.update_state(state=states.IGNORED)
            raise Ignore()
        return AlerterStatus.Recovering

    def on_success_operation(self, alerter_operation_data, current_status, kwargs):
        return AlerterStatus.Recovered

    def on_failure_operation(self, task_id, alerter_operation_data, current_status, retval, kwargs):
        return AlerterStatus.Recovered

    def on_retry_operation(self, task_id, alerter_operation_data, current_status, exc, einfo, kwargs):
        return True
