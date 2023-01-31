from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from alerta.models.alert import Alert
from iometrics_alerta import VarDefinition, ContextualConfiguration, merge
from iometrics_alerta.plugins import getLogger  # noqa


class RecoveryActionsResponseStatus(int, Enum):
    WAITING_RESPONSE = 0
    RESPONSE_OK = 1
    RESPONSE_ERROR = 2  # Retry will be done (if max retries not reached)


@dataclass
class RecoveryActionsResponse:
    status: RecoveryActionsResponseStatus
    operation_id: Optional[str] = None
    """
    Job id that will be used for async implementations where the actions are executed asynchronously. 
    This id will be used to ask for the current job status.
    """
    response_data: dict = field(default_factory=dict)
    """
    Dictionary with useful information to store within the alert.
    """
    finish_time: Optional[datetime] = None
    """
    Instant when the recovery actions finished. If provided, it should be a timezone-aware datetime object.
    """


class RecoveryActionsProvider(ABC):
    """
    Provider involved in executing recovery actions.
    """

    def __init__(self, name, app_config):
        super().__init__()
        self.app_config = app_config
        default_config = self.get_default_config() or {}
        config = self.get_config(f"RA_PROVIDER_{name.upper()}_CONFIG") or {}
        self.config = merge(default_config, config)

    def get_config(self, var_name, type_=None, default=None):
        var = VarDefinition(var_name, var_type=type_, default=default)
        return ContextualConfiguration.get_global_configuration(var, self.app_config)

    @abstractmethod
    def execute_actions(self, alert: Alert, actions: list, recovery_actions_config: dict,
                        retry_operation_id=None) -> RecoveryActionsResponse:
        """
        Launch provider to execute actions.
        Implementation must return a RecoveryActionResponse object indicating if the operation has finished ok or
        failing or if it is an asynchronous operation. In the last case manager will invoke get_execution_status
        with the response operation_id until operation finished (or timeout is reached).

        A failing response will imply a retry if max_retries are not reached. If no retry is needed because the
        failure cannot be resolved, an exception should be raised (with a different type or the Retryable Exceptions).

        :param alert:
        :param actions:
        :param recovery_actions_config:
        :param retry_operation_id: A preivous operation id was returned but execution failed.
        :return:
        """
        pass

    @abstractmethod
    def get_execution_status(self, alert_id: str, operation_id: str) -> RecoveryActionsResponse:
        """
        Launch provider to execute actions.
        Implementation must return a RecoveryActionResponse object indicating if the operation has finished ok or
        failing or if it is an asynchronous operation. In the last case manager must invoke get_status with the
        response operation_id until operation finished (or timeout is reached).

        A failing response will imply a retry (if max_retries are not reached) of the execute_actions operation.
        If no retry is needed because the failure cannot be resolved, an exception should be raised
        (with a different type from the Retryable Exceptions).

        A RetryableException will do nothing. Simply this request is ignored and will try with next one
        (if timeout is not reached).

        :param alert_id:
        :param operation_id:
        :return:
        """
        pass

    @abstractmethod
    def get_default_config(self) -> dict:
        """
        Provides a default configuration dictionary to merge with actual configuration.
        """
        pass
