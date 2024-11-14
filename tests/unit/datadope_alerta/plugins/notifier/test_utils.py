from copy import deepcopy
from datetime import datetime

import pytest

from datadope_alerta.backend.flexiblededup.models.rules import ContextualRule
from datadope_alerta.plugins.notifier.utils import compare_rules, compare_condition, compare_conditions


class TestUtils:
    SOURCE_DICT = {
            "resource": "res1",
            "event": "event1",
            "attributes": {
                "attr1": "valor1",
                "attr2": "varlor2",
                "attr3": 3,
                "attr4": {
                    "inner1": "valor_inner1"
                }
            },
            "tags": ["tag1", "tag2"]
        }
    @pytest.fixture
    def source(self):
        return deepcopy(self.SOURCE_DICT)

    @pytest.fixture
    def conditions(self):
        return [
            ContextualRule(
                name="Rule 1",
                contextual_rules=[{"resource": "res1"}],
                context={"text": "Matched Rule 1"}
            ),
            ContextualRule(
                name="Rule 2",
                contextual_rules=[{"resource": "res1", "attributes": {"attr1": "valor1"}}],
                context={"text": "Matched Rule 2"}
            ),
            ContextualRule(
                name="Rule 3",
                contextual_rules=[{"resource": "res1", "attributes": {"attr1": "valor1"}, "tags": ["tag1"]}],
                context={"text": "Matched Rule 3", "attributes": {"rule3": True}}
            ),
            ContextualRule(
                name="Rule 4",
                contextual_rules=[{"createTime": {"$gt": datetime.now()}}],
                context={"text": "Matched Rule 4"}
            ),
            ContextualRule(
                name="Rule 5",
                contextual_rules=[{"try": "try1"}, {"resource": "res1", "event": "event1"}, {"try": "try2"}],
                context={"text": "Matched Rule 5"}
            ),
            ContextualRule(
                name="Rule 6",
                contextual_rules=[{"resource": "res2"}],
                context={"text": "Matched Rule 6"}
            ),
            ContextualRule(
                name="Rule 7",
                contextual_rules=[{"attributes": {"attr1": "valor2"}}],
                context={"text": "Matched Rule 7"}
            ),
            ContextualRule(
                name="Rule 8",
                contextual_rules=[{"tags": ["tag3"]}],
                context={"text": "Matched Rule 8"}
            )
        ]

    @pytest.fixture
    def conditions_with_sets(self):
        return [
            ContextualRule(
                name="Rule 1",
                contextual_rules=[{"resource": "res1"}],
                context={"text": "Matched Rule 1"}
            ),
            ContextualRule(
                name="Rule 2",
                contextual_rules=[{"resource": "res1", "attributes": {"attr1": "valor1"}}],
                context={"text": "Matched Rule 2"}
            ),
            ContextualRule(
                name="Rule 3",
                contextual_rules=[{"resource": "res1", "attributes": {"attr1": "valor1"}, "tags": ["tag1"]}],
                context={"tags": ["tag3", "tag4"]}
            )
        ]

    @pytest.fixture
    def conditions_with_different_attributes(self):
        return [
            ContextualRule(
                name="Rule 1",
                contextual_rules=[{"resource": "res1"}],
                context={"text": "Matched Rule 1"}
            ),
            ContextualRule(
                name="Rule 2",
                contextual_rules=[{"resource": "res1", "attributes": {"attr1": "valor_not_matched"}}],
                context={"text": "Matched Rule 2"}
            ),
            ContextualRule(
                name="Rule 3",
                contextual_rules=[{"resource": "res1", "attributes": {"attr1": "valor1"}}, {"tags": ["tag1"]}],
                context={"tags": ["tag3", "tag4"]}
            )
        ]

    @pytest.fixture
    def conditions_with_different_attributes_changed(self):
        return [
            ContextualRule(
                name="Rule 1",
                contextual_rules=[{"resource": "res1"}],
                context={"text": "Matched Rule 1"}
            ),
            ContextualRule(
                name="Rule 2",
                contextual_rules=[{"resource": "res1", "attributes": {"attr1": "valor1"}}],
                context={"text": "Matched Rule 2"}
            ),
            ContextualRule(
                name="Rule 3",
                contextual_rules=[{"tags": ["tag3"]}, {"resource": "res1", "attributes": {"attr1": "valor1"}}],
                context={"tags": ["tag3", "tag4"]}
            )
        ]

    @pytest.fixture
    def conditions_with_lists(self):
        return [
            ContextualRule(
                name="Rule 1",
                contextual_rules=[{"resource": "res1"}],
                context={"text": "Matched Rule 1"}
            ),
            ContextualRule(
                name="Rule 2",
                contextual_rules=[{"resource": "res1", "attributes": {"attr1": "valor2"}}],
                context={"text": "Matched Rule 2", "tags": ["tag1"]}
            ),
            ContextualRule(
                name="Rule 3",
                contextual_rules=[{"resource": "res1", "attributes": {"attr1": "valor1"}, "tags": "tag2"}],
                context={"text": "Matched Rule 3", "tags": ["tag1"]},
                append_lists=False
            )
        ]

    def test_compare_conditions_with_sets(self, source, conditions_with_sets):
        assert compare_conditions(source, conditions_with_sets) == \
               { **source, **{"text": "Matched Rule 2", "tags": ["tag1", "tag2", "tag3", "tag4"]} }

    def test_compare_conditions_with_different_attributes(self, source, conditions_with_different_attributes):
        assert compare_conditions(source, conditions_with_different_attributes) == \
               { **source, **{"text": "Matched Rule 1", "tags": ["tag1", "tag2", "tag3", "tag4"]} }

    def test_compare_conditions_with_different_attributes_changed(self, source,
                                                                  conditions_with_different_attributes_changed):
        assert compare_conditions(source, conditions_with_different_attributes_changed) == \
               { **source, **{"text": "Matched Rule 2", "tags": ["tag1", "tag2", "tag3", "tag4"]} }

    def test_compare_conditions_with_lists(self, source, conditions_with_lists):
        assert (compare_conditions(source, conditions_with_lists) ==
                { **source, **{"text": "Matched Rule 3", "tags": ["tag1"]} })

    def test_compare_conditions(self, source, conditions):
        expected = {**source, **{"text": "Matched Rule 5"}}
        expected["attributes"]["rule3"] = True
        assert compare_conditions(source, conditions) == expected

    def test_compare_condition(self, source, conditions):
        assert compare_condition(source, conditions[0]) == {"text": "Matched Rule 1"}
        assert compare_condition(source, conditions[1]) == {"text": "Matched Rule 2"}
        assert compare_condition(source, conditions[2]) == {
            "text": "Matched Rule 3",
            "attributes": {"rule3": True}
        }
        assert compare_condition(source, conditions[3]) == {}
        assert compare_condition(source, conditions[4]) == {"text": "Matched Rule 5"}
        assert compare_condition(source, conditions[5]) == {}
        assert compare_condition(source, conditions[6]) == {}
        assert compare_condition(source, conditions[7]) == {}

    def test_compare_rules(self):
        source = {
            "resource": "res1",
            "event": "event1",
            "attributes": {
                "attr1": "valor1",
                "attr2": "varlor2",  # noqa
                "attr3": 3,
                "attr4": {
                    "inner1": "valor_inner1"
                }
            },
            "tags": ["tag1", "tag2"]
        }
        rule1 = {"resource": "res1"}
        rule2 = {"resource": "res1", "attributes": {"attr1": "valor1"}}
        rule3 = {"resource": "res1", "attributes": {"attr1": "valor1"}, "tags": ["tag1"]}
        rule4 = {"createTime": datetime.now()}
        rule5 = {"resource": "res1", "event": "event1"}
        rule6 = {"resource": "res2"}
        rule7 = {"attributes": {"attr1": "valor2"}}
        rule8 = {"tags": ["tag3"]}
        assert compare_rules(source, rule1) is True
        assert compare_rules(source, rule2) is True
        assert compare_rules(source, rule3) is True
        assert compare_rules(source, rule4) is False
        assert compare_rules(source, rule5) is True
        assert compare_rules(source, rule6) is False
        assert compare_rules(source, rule7) is False
        assert compare_rules(source, rule8) is False
