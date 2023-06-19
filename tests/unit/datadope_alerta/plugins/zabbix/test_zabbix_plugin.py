import logging
from unittest.mock import patch, call

# noinspection PyPackageRequirements
import pytest

from alerta.models.alert import Alert
from datadope_alerta.plugins.zabbix.zabbix_plugin import ZabbixBasePlugin, ZabbixAlerter


@pytest.fixture
def logger():
    yield logging.getLogger('datadope_alerta.plugins.zabbix.zabbix_plugin')


@pytest.fixture()
def config():
    config = pytest.app.config
    config['ZABBIX_CONFIG'] = {
        "platform_field": "origin",
        "supported_platforms": "zabbix",
        "zabbix_reference_attributes": [
            "zabbixEventId",
            "eventId"
        ]
    }
    yield config

@pytest.fixture
def alert_supported_no_alerter():
    yield Alert(event='NodeDown',
                resource='testing_server',
                id='4981cf48-254f-4e88-8396-027f91dff104',
                environment='Production',
                severity='critical',
                status='open',
                origin='zabbix',
                attributes={
                    'alerters': ['gchat']
                })


@pytest.fixture
def alert_supported_with_alerter():
    yield Alert(event='NodeDown',
                resource='testing_server',
                id='4981cf48-254f-4e88-8396-027f91dff104',
                environment='Production',
                severity='critical',
                status='open',
                origin='zabbix',
                attributes={
                    'alerters': ['gchat', 'zabbix'],
                    'zabbixEventId': '111'
                })


@pytest.fixture
def alert_not_supported():
    yield Alert(event='NodeDown',
                resource='testing_server',
                id='4981cf48-254f-4e88-8396-027f91dff104',
                environment='Production',
                severity='critical',
                status='open',
                origin='no_zabbix',
                attributes={
                    'alerters': ['gchat']
                })


def test_pre_receive_supported_no_alerter(alert_supported_no_alerter, config):
    obj = ZabbixBasePlugin('zabbix_base')
    alert = obj.pre_receive(alert_supported_no_alerter, config=config)
    assert alert.attributes['alerters'] == ['gchat', 'zabbix']


def test_pre_receive_supported_with_alerter(alert_supported_with_alerter, config):
    obj = ZabbixBasePlugin('zabbix_base')
    alert = obj.pre_receive(alert_supported_with_alerter, config=config)
    assert alert.attributes['alerters'] == ['gchat', 'zabbix']


def test_pre_receive_not_supported(alert_not_supported, config):
    obj = ZabbixBasePlugin('zabbix_base')
    alert = obj.pre_receive(alert_not_supported, config=config)
    assert alert.attributes['alerters'] == ['gchat']


@patch('datadope_alerta.plugins.zabbix.zabbix_plugin.ExternalReferences')
def test_post_receive(mocked_be, alert_supported_with_alerter, config):
    mocked_be_instance = mocked_be.return_value
    mocked_be_instance.get_references.return_value = ['110', '111']
    obj = ZabbixBasePlugin('zabbix_base')
    alert = obj.post_receive(alert_supported_with_alerter, config=config)
    mocked_be_instance.insert.assert_called_once_with(alert_supported_with_alerter.id, 'zabbix', '111')
    assert alert.attributes['zabbixReferences'] == ['110', '111']


@pytest.mark.parametrize(('api_token', 'user', 'password', 'verify_ssl', 'timeout', 'not_found'),
                         [
                             ('the_token', 'user', 'password', None, None, False),
                             (None, 'user', 'password', True, 10.5, False),
                             (None, 'user', 'password', False, 10.5, True),
                          ])
@patch('datadope_alerta.plugins.zabbix.zabbix_plugin.ZabbixAPI')
@patch('datadope_alerta.plugins.zabbix.zabbix_plugin.ExternalReferences')
def test_process_recovery(mocked_be, mocked_zabbix, alert_supported_with_alerter, config,
                          api_token, user, password, verify_ssl, timeout, not_found):
    reason = "The reason"
    config['ZABBIX_CONFIG']['zabbix_connection'] = {
        "url": "http://zabbix",
        "user": user,
        "password": password,
    }
    if api_token:
        config['ZABBIX_CONFIG']['zabbix_connection']["api_token"] = api_token
    if verify_ssl is not None:
        config['ZABBIX_CONFIG']['zabbix_connection']["verify_ssl"] = verify_ssl
    if timeout:
        config['ZABBIX_CONFIG']['zabbix_connection']["timeout"] = timeout
    mocked_be_instance = mocked_be.return_value
    mocked_be_instance.get_references.return_value = ['110', '111']
    mocked_zabbix_instance = mocked_zabbix.return_value
    mocked_zabbix_instance.event.acknowledge.side_effect = [
        {"eventids": ['110']},
        {"eventids": [] if not_found else ['111']}]
    ZabbixAlerter._alerter_config = None
    obj = ZabbixAlerter('zabbix')
    response = obj.process_recovery(alert=alert_supported_with_alerter, reason=reason)
    mocked_zabbix.assert_called_once_with("http://zabbix", timeout=timeout if timeout else 12.1)
    if verify_ssl is False:
        assert mocked_zabbix_instance.session.verify == False
    if api_token:
        mocked_zabbix_instance.login.assert_called_once_with(api_token=api_token)
    else:
        mocked_zabbix_instance.login.assert_called_once_with(user=user, password=password)
    mocked_zabbix_instance.event.acknowledge.assert_has_calls([
        call(eventids='110', action=5, message=f"Alert '{alert_supported_with_alerter.id}' closed in IOMetrics Alerta"),
        call(eventids='111', action=5, message=f"Alert '{alert_supported_with_alerter.id}' closed in IOMetrics Alerta")
    ])
    assert response == (True, {'events_to_close': ['110', '111'],
                               'result': {
                                   '110': 'Closed',
                                   '111': 'Not found' if not_found else'Closed'
                               }})


@patch('datadope_alerta.plugins.zabbix.zabbix_plugin.ExternalReferences')
@patch('logging.Logger.warning')
def test_process_recovery_fail_login(mock_logger_warning, mocked_be,
                                     alert_supported_with_alerter, config):
    reason = "The reason"
    config['ZABBIX_CONFIG']['zabbix_connection'] = {
        "url": "http://zabbix",
        "user": None,
    }
    mocked_be_instance = mocked_be.return_value
    mocked_be_instance.get_references.return_value = ['110', '111']
    ZabbixAlerter._alerter_config = None
    obj = ZabbixAlerter('zabbix')
    response = obj.process_recovery(alert=alert_supported_with_alerter, reason=reason)
    mock_logger_warning.assert_called_once_with("Missing some connection configuration for platform '%s'", 'zabbix')
    assert response == (False, {'reason': 'Wrong configuration',
                                'info': {
                                    'message': "Missing some connection configuration for platform 'zabbix'"
                                }})


@patch('logging.Logger.debug')
def test_process_recovery_wrong_platform(mock_logger_debug, alert_supported_with_alerter, config):
    reason = "The reason"
    alert_supported_with_alerter.origin = 'wrong_platform'
    ZabbixAlerter._alerter_config = None
    obj = ZabbixAlerter('zabbix')
    response = obj.process_recovery(alert=alert_supported_with_alerter, reason=reason)
    mock_logger_debug.assert_called_once_with("Platform '%s' not supported by plugin. Ignoring recovery execution",
                                              'wrong_platform')
    assert response == (True, {})


@patch('logging.Logger.debug')
def test_process_recovery_no_platform(mock_logger_debug,
                                         alert_supported_with_alerter, config):
    reason = "The reason"
    alert_supported_with_alerter.origin = None
    ZabbixAlerter._alerter_config = None
    obj = ZabbixAlerter('zabbix')
    response = obj.process_recovery(alert=alert_supported_with_alerter, reason=reason)
    mock_logger_debug.assert_called_once_with("Platform field not filled. Ignoring recovery execution")
    assert response == (True, {})


@patch('datadope_alerta.plugins.zabbix.zabbix_plugin.ExternalReferences')
def test_process_recovery_no_events(mocked_be, alert_supported_with_alerter, config):
    reason = "The reason"
    config['ZABBIX_CONFIG']['zabbix_connection'] = {
        "url": "http://zabbix",
        "user": None,
    }
    mocked_be_instance = mocked_be.return_value
    mocked_be_instance.get_references.return_value = []
    ZabbixAlerter._alerter_config = None
    obj = ZabbixAlerter('zabbix')
    response = obj.process_recovery(alert=alert_supported_with_alerter, reason=reason)
    assert response == (True, {'events_to_close': [], 'result': {}})
