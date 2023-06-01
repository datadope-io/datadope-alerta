from math import ceil
from unittest.mock import patch

import pytest
from flask import jsonify, Response

from alerta.models.alert import Alert
from datadope_alerta.backend.flexiblededup.models.rules import ContextualRule
from datadope_alerta.plugins.notifier.notifier_plugin import NotifierPlugin


def contextual_rules_list(size: int, match_case: int) -> list[ContextualRule]:
    rules = []
    for i in range(0, int(size / 2)):
        if match_case == 1:
            rules.extend(get_contextual_rules_match_1())
        if match_case == 4:
            rules.extend(get_contextual_rules_match_4())
        if match_case == 8:
            rules.extend(get_contextual_rules_match_8())
        if match_case == 0:
            rules.extend(get_contextual_rules_no_match())
    return rules


def get_contextual_rules_match_1():
    return [ContextualRule(
        name="Rule 101",
        contextual_rules=[{"resource": "test_resource"}],
        context={"text_no": "Matched Rule 101"}
    ), ContextualRule(
        name="Rule 1022",
        contextual_rules=[{"resource": "res1", "attributes": {"attr1": "valor1"}}],
        context={"text": "Matched Rule 102", "attributes": {"attr1": "valor1"}}
    )]


def get_contextual_rules_match_4():
    return [ContextualRule(
        name="Rule 103",
        contextual_rules=[{"no_match": "res1"}, {"no_match2": "res2"}, {"no_match3": "res3"},
                          {"resource": "test_resource", "attributes": {"attr1": "valor1"}, "tags": ["tag1"]}],
        context={"resource": 1, "attributes": {"attr1": "valor1"}}
    ), ContextualRule(
        name="Rule 104",
        contextual_rules=[{"no_match": "res1"}, {"no_match2": "res2"}, {"no_match3": "res3"},
                          {"resource": "test_resource", "attributes": {"attr1": "valor1"}, "tags": ["tag1"]}],
        context={"text": "Matched Rule 104", "tags": ["tag1", "tag2"]}
    )]


def get_contextual_rules_match_8():
    return [ContextualRule(
        name="Rule 105",
        contextual_rules=[{"no_match": "res1"}, {"no_match2": "res2"}, {"no_match3": "res3"},
                          {"no_match4": "res4"}, {"no_match5": "res5"}, {"no_match6": "res6"},
                          {"no_match7": "res7"},
                          {"resource": "test_resource", "attributes": {"attr1": "valor1"}, "tags": ["tag1"]}],
        context={"event": "Matched Rule 105", "attributes": {"attr1": "valor1"}}
    ), ContextualRule(
        name="Rule 106",
        contextual_rules=[{"no_match": "res1"}, {"no_match2": "res2"}, {"no_match3": "res3"},
                          {"no_match4": "res4"}, {"no_match5": "res5"}, {"no_match6": "res6"},
                          {"no_match7": "res7"},
                          {"resource": "test_resource", "attributes": {"attr1": "valor1"}, "tags": ["tag1"]}],
        context={"value": "Matched Rule 106", "tags": [{"tag1": "tag1"}, {"tag2": "tag2"}]}
    )]


def get_contextual_rules_no_match():
    return [ContextualRule(
        name="Rule 202",
        contextual_rules=[{"resources": "test_resource", "attributtes": {"attr1": "valor1"}}],  # noqa
        context={"messahjkge": "no match"}
    ), ContextualRule(
        name="Rule 203",
        contextual_rules=[{"resources": "test_resource", "attributtes": {"attr1": "valor1"}, "taggs": ["tag1"]}],
        # noqa
        context={"messhnjmage": "no match"}
    )]


# noinspection PyProtectedMember,SpellCheckingInspection
class TestPerformance:

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
                "attr1": "valor1",
                "message": "test_message",
            },
            tags=["tag1"],
            text='test_text',
            )

    @patch('datadope_alerta.plugins.notifier.notifier_plugin.ContextualizerAPI')
    @pytest.mark.parametrize('size, match_case', [
        (10, 1), (10, 4), (10, 8), (10, 0),
        (100, 1), (100, 4), (100, 8), (100, 0),
        (1000, 1), (1000, 4), (1000, 8), (1000, 0),
        (10000, 1), (10000, 4), (10000, 8), (10000, 0),
        (100000, 1), (100000, 4), (100000, 8), (100000, 0),
    ])
    def test_contextual_rules(self, mock_contextualizer_api, get_app, get_notifier, get_alert,
                              size, match_case):
        """
        This test is executed once for every tuple marked above, changing in size and type of
        rule to be matched each time the test is run.
        """
        all_rules = contextual_rules_list(size=size, match_case=match_case)
        loops = 0
        global_limit = 0

        def read_all_rules_mock(limit=50, offset=0) -> Response:
            rules = all_rules[offset:limit + offset]
            nonlocal loops, global_limit
            global_limit = limit
            loops += 1
            return jsonify([i.__dict__ for i in rules])

        mock_contextualizer_api.read_all_rules.side_effect = read_all_rules_mock
        get_notifier.pre_receive(alert=get_alert)
        result = ceil(float(size) / global_limit)

        if (size % global_limit) == 0:
            result += 1

        assert loops == result
