import datetime
from unittest.mock import patch

import pytest
from flask import jsonify, Response
from alerta.utils.format import DateTime

from alerta.models.alert import Alert
from datadope_alerta.backend.flexiblededup.models.rules import ContextualRule
from datadope_alerta.plugins.notifier.notifier_plugin import NotifierPlugin


# noinspection SpellCheckingInspection
class TestNotifierPlugin:

    @pytest.fixture()
    def get_notifier(self, get_app):
        return NotifierPlugin()

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
                'alerters': 'notifier,test_async',
                'eventTags': '{ "test_tag": "test_value", "test_tag2": "test_value2" }',
            },
            text='test_text')

    @pytest.fixture()
    def get_alert_final_result(self, get_alert) -> Alert:
        get_alert.attributes = {
            'alerters': 'notifier,test_async',
            'eventTags': '{ "test_tag": "test_value", "test_tag2": "test_value2" }',
        }
        get_alert.message = "Matched Rule 1"
        get_alert.tags = {"tag1", "tag2"}
        return get_alert

    @pytest.fixture()
    def get_contextual_rules(self) -> list:
        return [ContextualRule(
            name="Rule 1",
            contextual_rules=[{"resource": "res1"}],
            context={"message": "Matched Rule 1"}
        ), ContextualRule(
            name="Rule 2",
            contextual_rules=[{"resource": "res1", "attributes": {"attr1": "valor1"}}],
            context={"message": "Matched Rule 2"}
        ), ContextualRule(
            name="Rule 3",
            contextual_rules=[{"resource": "res1", "attributes": {"attr1": "valor1"}, "tags": ["tag1"]}],
            context={"message": "Matched Rule 3"}
        )]

    @pytest.fixture()
    def get_contextual_rules_2(self) -> list:
        return [ContextualRule(
            name="Rule 1",
            contextual_rules=[{"resource": "test_resource"}],
            context={"message": "Matched Rule 1",
                     "event": "modified",
                     "timeout": 10,
                     "create_time": "2023-05-18T11:00:00.000Z",
                     "attributes": {"alerters": "modified", "other_attr": "value"},
                     "tags": ["second"],
                     "group": None,
                     "service": ["the_service"],
                     "correlate": "a_string_that_has_to_fail"}
        ), ContextualRule(
            name="Rule 2",
            contextual_rules=[{"resource": "test_resource", "attributes": {"attr1": "valor1"}}],
            context={"message": "Matched Rule 2"}
        ), ContextualRule(
            name="Rule 3",
            contextual_rules=[{"resource": "test_resource", "attributes": {"attr1": "valor1"}, "tags": ["tag1"]}],
            context={"tags": ["tag1", "tag2"]}
        ), ContextualRule(
            name="Rule 4",
            contextual_rules=[{"no": "res1", "no_match": {"attr1": "valor1"}, "tagss": ["tag1"]}],
            context={"tags": ["tag1", "tag2"]}
        )]

    @pytest.fixture()
    def get_contextual_rules_none(self):
        return []

    @patch('datadope_alerta.plugins.notifier.notifier_plugin.ContextualRule')
    def test_get_conditions_less_rules_than_limit(self, mock_contextualizer_api, get_notifier,
                                                  get_contextual_rules):
        def read_all_rules_mock(limit=50, offset=0) -> list[ContextualRule]:
            return get_contextual_rules[offset:limit + offset]

        mock_contextualizer_api.all_from_db.side_effect = read_all_rules_mock
        assert len(get_notifier.get_conditions(page=5)) == len(get_contextual_rules)

    @patch('datadope_alerta.plugins.notifier.notifier_plugin.ContextualRule')
    def test_get_conditions_more_rules_than_limit(self, mock_contextualizer_api, get_notifier,
                                                  get_contextual_rules):
        def read_all_rules_mock(limit=50, offset=0) -> list[ContextualRule]:
            return get_contextual_rules[offset:limit + offset]


        mock_contextualizer_api.all_from_db.side_effect = read_all_rules_mock
        assert len(get_notifier.get_conditions(page=2)) == len(get_contextual_rules)

    @patch('datadope_alerta.plugins.notifier.notifier_plugin.ContextualRule')
    def test_get_conditions_same_number_of_rules_and_limit(self, mock_contextualizer_api, get_notifier,
                                                           get_contextual_rules):
        def read_all_rules_mock(limit=50, offset=0) -> list[ContextualRule]:
            return get_contextual_rules[offset:limit + offset]

        mock_contextualizer_api.all_from_db.side_effect = read_all_rules_mock
        assert len(get_notifier.get_conditions(page=3)) == len(get_contextual_rules)

    @patch('datadope_alerta.plugins.notifier.notifier_plugin.ContextualRule')
    def test_get_conditions_no_rules(self, mock_contextualizer_api, get_notifier, get_contextual_rules_none):
        def read_all_rules_mock(limit=50, offset=0) -> list[ContextualRule]:
            return get_contextual_rules_none[offset:limit + offset]

        mock_contextualizer_api.all_from_db.side_effect = read_all_rules_mock
        assert len(get_notifier.get_conditions(page=3)) == len(get_contextual_rules_none)

    @patch('datadope_alerta.plugins.notifier.notifier_plugin.ContextualRule')
    def test_get_pre_receive(self, mock_contextualizer_api, get_notifier, get_alert, get_contextual_rules_2):
        def read_all_rules_mock(limit=50, offset=0) -> list[ContextualRule]:
            return get_contextual_rules_2[offset:limit + offset]

        mock_contextualizer_api.all_from_db.side_effect = read_all_rules_mock
        assert get_alert.event == "test_event"
        get_alert.timeout = 111111
        get_alert.create_time = datetime.datetime.utcnow()
        get_alert.tags = ["first"]
        get_alert.service = None
        get_alert.correlate = []

        get_notifier.pre_receive(alert=get_alert)

        assert get_alert.correlate == []
        assert get_alert.group is None
        assert get_alert.service == ["the_service"]
        assert get_alert.event == "modified"
        assert get_alert.timeout == 10
        assert get_alert.create_time == DateTime.parse("2023-05-18T11:00:00.000Z")
        assert get_alert.attributes == {
            "alerters": "modified",
            'eventTags': '{ "test_tag": "test_value", "test_tag2": "test_value2" }',
            "other_attr": "value"
        }
        assert get_alert.tags == ["first", "second"]
        try:
            getattr(get_alert, "message")
            assert False, "'message' shouldn't be defined"
        except AttributeError:
            pass

    @patch('datadope_alerta.plugins.notifier.notifier_plugin.ContextualRule')
    def test_get_pre_receive_none(self, mock_contextualizer_api, get_notifier, get_alert,
                                  get_contextual_rules_none):
        def read_all_rules_mock(limit=50, offset=0) -> list[ContextualRule]:
            return get_contextual_rules_none[offset:limit + offset]

        mock_contextualizer_api.all_from_db.side_effect = read_all_rules_mock
        assert get_notifier.pre_receive(alert=get_alert) == get_alert

    def test_post_receive(self, get_notifier, get_alert):
        assert get_notifier.post_receive(alert=get_alert) is None

    def test_status_change(self, get_notifier, get_alert):
        assert get_notifier.status_change(alert=get_alert, status='test_status', text='test_text') is None

    def test_take_action(self, get_notifier, get_alert):
        assert get_notifier.take_action(alert=get_alert, action='test_action', text='test_text') is None

    def test_take_note(self, get_notifier, get_alert):
        assert get_notifier.take_note(alert=get_alert, text='test_text') is None

    def test_delete(self, get_notifier, get_alert):
        assert get_notifier.delete(alert=get_alert) is True
