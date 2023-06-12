from unittest.mock import patch

import pytest
from requests import Response

from alerta.models.alert import Alert
from datadope_alerta.plugins.cmdb_context.cmdb_context import CMDBContextPlugin


# noinspection SpellCheckingInspection
class TestCMDBContextPlugin:

    @pytest.fixture()
    def get_context_plugin(self, get_app):
        return CMDBContextPlugin()

    @pytest.fixture()
    def get_alert(self) -> Alert:
        return Alert(
            resource='test_resource',
            event='test_event',
            environment='test_environment',
            severity='major',
            service='test_service',
            group='test_group',
            value='test_message',
            attributes={
                'alerters': 'cmdb_context'
            },
            text='test_text')

    @pytest.fixture()
    def cmdb_info_and_watchers(self):
        response = Response()
        response.status_code = 200
        response._content = b'{"test_resource":{"data":{"env":"Producci\xc3\xb3n","env_code":"Produccion",' \
                            b'"cmdb_id":2667100,"cmdb_class":"Server","services":{' \
                            b'"2375d776911d3175d86b51f767f95c01":{"name":"CMDB","cmdb_id":15830577,"components":{' \
                            b'"692b8eb5df306e4dc0f25c311184b72a":{"name":"CMDBuild","cmdb_id":15830805,"instances":{' \
                            b'"dd576d739f3ef78cc3f5e104810692a2":{"environment":"Producci\xc3\xb3n",' \
                            b'"environment_code":"Produccion","cmdb_id":15837203}}},' \
                            b'"78f64a0ef209b275d0ec77ca5549d01e":{"name":"IOMetrics CMDB-API","cmdb_id":15830839,' \
                            b'"instances":{"39d6a1ac2e3184655c8d0581c3c08c01":{"environment":"Producci\xc3\xb3n",' \
                            b'"environment_code":"Produccion","cmdb_id":15837241}}},' \
                            b'"6f158b5c5f1a588b27e1169ceaceda12":{"name":"IOMetrics CMDB-Bridge","cmdb_id":15830876,' \
                            b'"instances":{"867943d85e66e225967d233e0648ebba":{"environment":"Producci\xc3\xb3n",' \
                            b'"environment_code":"Produccion","cmdb_id":15837273}}}}}}},' \
                            b'"watchers":["test.test@test.com"]}}'
        return response

    @pytest.fixture()
    def cmdb_info_and_watchers_item_not_found(self):
        response = Response()
        response.status_code = 404
        response._content = b'{"detail":"CI with Code test_resource not found"}'
        return response

    @pytest.fixture()
    def cmdb_info_and_watchers_no_data(self):
        response = Response()
        response.status_code = 200
        response._content = b'{"test_resource": {"watchers":{}}}'
        return response

    @pytest.fixture()
    def cmdb_info_and_watchers_error_response(self):
        response = Response()
        response.status_code = 500
        response._content = b'{"error":"an error ocurred while processing the petition"}'
        return response

    @pytest.fixture()
    def cmdb_info_and_watchers_bad_response(self):
        response = {"test_resource": {
            "data": {
                "env": "Producci\xc3\xb3n", "env_code": "Produccion", "cmdb_id": 2667100, "cmdb_class": "Server",
                "services": {
                    "2375d776911d3175d86b51f767f95c01": {
                        "name": "CMDB", "cmdb_id": 15830577, "components": {
                            "692b8eb5df306e4dc0f25c311184b72a": {
                                "name": "CMDBuild", "cmdb_id": 15830805,
                                "instances": {
                                    "dd576d739f3ef78cc3f5e104810692a2": {
                                        "environment": "Producci\xc3\xb3n",
                                        "environment_code": "Produccion",
                                        "cmdb_id": 15837203}}},
                            "78f64a0ef209b275d0ec77ca5549d01e": {
                                "name": "IOMetrics CMDB-API", "cmdb_id": 15830839,
                                "instances": {"39d6a1ac2e3184655c8d0581c3c08c01": {
                                    "environment": "Producci\xc3\xb3n",
                                    "environment_code": "Produccion",
                                    "cmdb_id": 15837241}}},
                            "6f158b5c5f1a588b27e1169ceaceda12": {
                                "name": "IOMetrics CMDB-Bridge", "cmdb_id": 15830876,
                                "instances": {"867943d85e66e225967d233e0648ebba": {
                                    "environment": "Producci\xc3\xb3n",
                                    "environment_code": "Produccion",
                                    "cmdb_id": 15837273}}}}}}},
            "watchers": ["test.test@test.com"]}}
        return response

    def test_pre_receive(self, get_context_plugin, get_alert, cmdb_info_and_watchers):
        alert = get_alert
        with patch('requests.get') as r:
            r.return_value = cmdb_info_and_watchers
            get_context_plugin.pre_receive(alert)
        assert alert.attributes['sendTo'] is not None
        assert alert.attributes['cmdbFunctionalInformation'] is not None
        assert alert.attributes['cmdbWatchers'] is not None
        assert 'test.test@test.com' in (alert.attributes['sendTo'])

    def test_pre_receive_item_not_found(self, get_context_plugin, get_alert, cmdb_info_and_watchers_item_not_found):
        alert = get_alert
        with patch('requests.get') as r:
            r.return_value = cmdb_info_and_watchers_item_not_found
            get_context_plugin.pre_receive(alert)
        assert True

    def test_pre_receive_error_response(self, get_context_plugin, get_alert, cmdb_info_and_watchers_error_response):
        alert = get_alert
        with patch('requests.get') as r:
            r.return_value = cmdb_info_and_watchers_error_response
            get_context_plugin.pre_receive(alert)
        assert True

    def test_pre_receive_no_data_in_response(self, get_context_plugin, get_alert, cmdb_info_and_watchers_no_data):
        alert = get_alert
        with patch('requests.get') as r:
            r.return_value = cmdb_info_and_watchers_no_data
            get_context_plugin.pre_receive(alert)
        assert True

    def test_pre_receive_exception(self, get_context_plugin, get_alert, cmdb_info_and_watchers_bad_response):
        alert = get_alert
        with patch('requests.get') as r:
            r.return_value = cmdb_info_and_watchers_bad_response
            get_context_plugin.pre_receive(alert)
        assert True

    def test_post_receive(self, get_context_plugin, get_alert):
        assert get_context_plugin.post_receive(alert=get_alert) is None

    def test_status_change(self, get_context_plugin, get_alert):
        assert get_context_plugin.status_change(alert=get_alert, status='test_status', text='test_text') is None

    def test_take_action(self, get_context_plugin, get_alert):
        assert get_context_plugin.take_action(alert=get_alert, action='test_action', text='test_text') is None

    def test_take_note(self, get_context_plugin, get_alert):
        assert get_context_plugin.take_note(alert=get_alert, text='test_text') is None

    def test_delete(self, get_context_plugin, get_alert):
        assert get_context_plugin.delete(alert=get_alert) is True
