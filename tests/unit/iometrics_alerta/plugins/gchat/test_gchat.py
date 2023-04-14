import pytest

from unittest.mock import patch
from alerta import create_app
from alerta.models.alert import Alert

from iometrics_alerta.plugins.gchat.gchat_plugin import GChatPlugin

from iometrics_alerta.plugins import getLogger

logger = getLogger(__name__)

TESTING_URLS = {
    'test_1': 'https://chat.googleapis.com/v1/spaces/test1',
    'test_2': 'https://chat.googleapis.com/v1/spaces/test2',
    'test_3': 'https://chat.googleapis.com/v1/spaces/test3'
}


class TestGchatMethods:

    @pytest.fixture()
    def setup_app(self):
        test_app = create_app()
        with(test_app.app_context()):
            yield

    @pytest.fixture()
    def setup_alerter(self, setup_app):
        return GChatPlugin().get_alerter_class()('gchat')

    @pytest.fixture()
    def get_alert(self, setup_app):
        return Alert(event='NodeDown', resource='testing_server', id='4981cf48-254f-4e88-8396-027f91dff104',
                     environment='Production', severity='critical', status='open',
                     attributes={'ip': '127.0.0.1',
                                 'alerters': ['gchat'],
                                 'eventTags': {
                                     'GCHAT': TESTING_URLS.get('test_1'),
                                     'HOST.HOST': 'host name',
                                     'TRIGGER.NAME': 'Trigger name',
                                     'TRIGGER.SEVERITY': 'critical'}})

    def test_get_default_configuration(self, setup_alerter):
        """
           GIVEN the alerter is being instantiated
           WHEN the config is being read
           THEN assert that the file can be read and it's contents are valid
        """
        config = setup_alerter.get_default_configuration()
        assert config is not None
        assert isinstance(config, dict)

    @pytest.mark.parametrize('input_element, response_value, result', [
        (TESTING_URLS['test_1'], 200, (True, {})),
        ([TESTING_URLS['test_2']], 200, (True, {})),
        (TESTING_URLS['test_3'], 401, (False, {})),
        ("", 500, (False, {})),
        (None, 500, (False, {}))])
    def test_process_event_and_process_recovery(self, setup_alerter, get_alert, input_element, response_value, result,
                                                requests_mock):
        """
           GIVEN an alert has been received.
           WHEN processing the alert as new one and as an old one.
           THEN assert that the process works as intended when:
                * the alert fields are all correctly fulfilled and the response from the api call is successful when
                  the GCHAT tag comes as a string of elements comma separated.
                * the alert fields are all correctly fulfilled and the response from the api call is successful when
                  the GCHAT tag comes as a list of elements.
                * the alert fields are all correctly fulfilled and the response from the api call is unsuccessful.
                * when the url to the GCHAT rooms is missing or None.
        """
        get_alert.attributes['eventTags']['GCHAT'] = input_element
        if input_element:
            requests_mock.post(
                input_element if not isinstance(input_element, list) else input_element[0],
                status_code=response_value
            )

        assert setup_alerter.process_event(get_alert, setup_alerter.process_event.__name__) == result
        assert setup_alerter.process_recovery(get_alert, setup_alerter.process_recovery.__name__) == result

    def test_process_event_and_process_recovery_fail_request_exception(self, setup_alerter, get_alert):
        """
          GIVEN an alert has been received.
          WHEN processing the alert as a new one.
          THEN assert that an error is raised when something unexpected
               went wrong.
       """
        get_alert.attributes['eventTags']['GCHAT'] = TESTING_URLS.get('test_1')
        with patch('requests.post') as post_mock:
            post_mock.side_effect = ConnectionError()
            with pytest.raises(Exception):
                setup_alerter.process_event(get_alert, setup_alerter.process_event.__name__)

    def test_process_event_and_process_recovery_fail_unexpected_exception(self, setup_alerter, get_alert):
        """
          GIVEN an alert has been received.
          WHEN processing the alert as a new one.
          THEN assert that an error is raised when something unexpected
               went wrong.
       """
        get_alert.attributes['eventTags']['GCHAT'] = {"GCHAT": ["", ""]}
        with pytest.raises(AttributeError):
            setup_alerter.process_event(get_alert, setup_alerter.process_event.__name__)

    def test_process_repeat(self, setup_alerter, get_alert):
        assert setup_alerter.process_repeat(get_alert, setup_alerter.process_repeat.__name__) == (True, {})

    def test_process_action(self, setup_alerter, get_alert):
        assert setup_alerter.process_action(get_alert, setup_alerter.process_action.__name__, action='Test_action') == (
            True, {})
