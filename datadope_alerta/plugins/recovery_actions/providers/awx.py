import json
from datetime import datetime

import requests

from datadope_alerta import NormalizedDictView, DateTime
from . import RecoveryActionsProvider, getLogger, RecoveryActionsResponse, RecoveryActionsResponseStatus

logger = getLogger(__name__)


HEADERS = {
    'Content-Type': 'application/json'
}


class Provider(RecoveryActionsProvider):

    def get_default_config(self) -> dict:
        return {
            "api_url": "http://127.0.0.1:8111/api/v2/",
            "user": "the_user",
            "password": "the_password",
            "verify_ssl": True,
            "default_template": 12
        }

    def execute_actions(self, alert, actions, recovery_actions_config,
                        retry_operation_id=None) -> RecoveryActionsResponse:
        if retry_operation_id:
            logger.info("Executing job '%s' again", retry_operation_id)
            return self.retry_job(retry_operation_id)
        else:
            logger.info("Executing actions '%s'", ', '.join(actions))
            return self.launch_new_job(alert, actions, recovery_actions_config)

    def get_execution_status(self, alert_id, operation_id) -> RecoveryActionsResponse:
        user = self.config['user']
        password = self.config['password']
        verify_ssl = self.config['verify_ssl']
        url = self.create_status_url(operation_id)
        response = requests.get(url=url, headers=HEADERS, auth=(user, password), verify=verify_ssl)
        try:
            json_response = response.json()
        except ValueError:
            json_response = None
        status_code = response.status_code
        response_info = {
            'info': {
                'status_code': status_code,
                'data': json_response or {}
            }
        }
        if status_code == 200 and json_response:
            job_status = json_response.get('status', 'not_available')
            if job_status == 'successful':
                logger.info("Job %s finished successfully", operation_id)
                response_info['info']['message'] = f"Job {operation_id} finished successfully"
                finish_time = self.get_finish_time(operation_id, json_response)
                return RecoveryActionsResponse(RecoveryActionsResponseStatus.RESPONSE_OK, operation_id,
                                               response_info, finish_time)

            elif job_status in ('failed', 'error'):
                logger.info("Job %s failed with status %s", operation_id, job_status)
                response_info['info']['message'] = f"Job {operation_id} failed with status {job_status}"
                finish_time = self.get_finish_time(operation_id, json_response)
                return RecoveryActionsResponse(RecoveryActionsResponseStatus.RESPONSE_ERROR, operation_id,
                                               response_info, finish_time)
            elif job_status == 'canceled':
                logger.info("Job %s was cancelled", operation_id)
                raise Exception(f"Job {operation_id} was cancelled")
            else:
                logger.info("Job '%s' still running (status = %s)", operation_id, job_status)
                response_info['info']['message'] = f"Job {operation_id} not finished yet"
                return RecoveryActionsResponse(RecoveryActionsResponseStatus.WAITING_RESPONSE, operation_id,
                                               response_info)
        else:
            logger.warning("Error (status_code: %d) getting job %d status: %s",
                           status_code, operation_id, json_response)
            if status_code == 404:
                response_info['info']['message'] = f"Job {operation_id} not found"
                return RecoveryActionsResponse(RecoveryActionsResponseStatus.RESPONSE_ERROR,
                                               operation_id=None,
                                               response_data=response_info)
            elif status_code == 403:
                response_info['info']['message'] = "Wrong credentials"
                return RecoveryActionsResponse(RecoveryActionsResponseStatus.RESPONSE_ERROR,
                                               operation_id=None,
                                               response_data=response_info)
            elif status_code == 400:
                response_info['info']['message'] = "Missing expected information"
                return RecoveryActionsResponse(RecoveryActionsResponseStatus.RESPONSE_ERROR,
                                               operation_id=None,
                                               response_data=response_info)
            else:
                response_info['info']['message'] = "Wrong response"
                return RecoveryActionsResponse(RecoveryActionsResponseStatus.RESPONSE_ERROR,
                                               operation_id=None,
                                               response_data=response_info)

    def launch_new_job(self, alert, actions, recovery_actions_config) -> RecoveryActionsResponse:
        data = json.dumps(self.create_awx_data(alert, actions, recovery_actions_config))
        url = self.create_launch_url(recovery_actions_config)
        return self.execute_job(url, data)

    def retry_job(self, job_id) -> RecoveryActionsResponse:
        data = {}
        url = self.create_relaunch_url(job_id)
        return self.execute_job(url, data)

    def execute_job(self, url, data):
        user = self.config['user']
        password = self.config['password']
        verify_ssl = self.config['verify_ssl']
        response = requests.post(url, data=data, headers=HEADERS, auth=(user, password), verify=verify_ssl)
        status_code = response.status_code
        try:
            json_response = response.json()
        except ValueError:
            json_response = None
        response_info = {
            'info': {
                'status_code': status_code,
                'data': json_response or {}
            }
        }
        if status_code in (200, 201) and json_response:
            job_id = str(json_response['job'])
            response_info['info']['message'] = "Success"
            return RecoveryActionsResponse(RecoveryActionsResponseStatus.WAITING_RESPONSE,
                                           operation_id=job_id,
                                           response_data=response_info)
        elif status_code == 403:
            response_info['info']['message'] = "Wrong credentials"
            return RecoveryActionsResponse(RecoveryActionsResponseStatus.RESPONSE_ERROR,
                                           operation_id=None,
                                           response_data=response_info)
        elif status_code == 400:
            response_info['info']['message'] = "Missing expected information"
            return RecoveryActionsResponse(RecoveryActionsResponseStatus.RESPONSE_ERROR,
                                           operation_id=None,
                                           response_data=response_info)
        else:
            response_info['info']['message'] = "Wrong response"
            return RecoveryActionsResponse(RecoveryActionsResponseStatus.RESPONSE_ERROR,
                                           operation_id=None,
                                           response_data=response_info)

    @staticmethod
    def create_awx_data(alert, role_list, job_config):
        tags = NormalizedDictView(job_config)
        host = tags.get('limit', alert.resource)
        if not host:
            exc = "NO LIMIT FOUND IN ALERT INFO. CANNOT EXECUTE TASK."
            logger.warning("%s", exc)
            raise Exception(exc)

        extra_vars = job_config.get('extra_vars', {})
        extra_tags = job_config.get('extra_tags', {})
        extra_vars_dict = {
            'event_id': alert.id,
            'ansible_action_type': 'recovery',
            'role_list': role_list,
            'tags_incidencias': extra_tags,
        }
        extra_vars_dict.update(extra_vars)
        data = {
            'limit': host,
            'extra_vars': extra_vars_dict
        }
        return data

    @staticmethod
    def get_finish_time(job_id, json_response):
        finish_time = None
        finish_time_str = json_response.get('finished')
        if finish_time_str:
            # noinspection PyBroadException
            try:
                finish_time = DateTime.parse_utc(finish_time_str)
            except Exception:
                logger.warning("Wrong finish time format for job '%s': '%s'", job_id, finish_time_str)
                finish_time = None
        if not finish_time:
            finish_time = DateTime.make_aware_utc(datetime.now())
        return finish_time

    def create_launch_url(self, job_config):
        url = self.config['api_url']
        template_id = job_config.get('template', self.config['default_template'])
        if not url.endswith('/'):
            url += '/'
        return f"{url}job_templates/{template_id}/launch/"

    def create_relaunch_url(self, job_id):
        url = self.config['api_url']
        if not url.endswith('/'):
            url += '/'
        url = f"{url}jobs/{job_id}/relaunch/"
        return url

    def create_status_url(self, job_id):
        url = self.config['api_url']
        if not url.endswith('/'):
            url += '/'
        url = f"{url}jobs/{job_id}/"
        return url
