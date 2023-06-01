from datetime import datetime

import pytest

from datadope_alerta.backend.flexiblededup.models.rules import ContextualRule
from datadope_alerta.plugins.notifier.utils import compare_rules, compare_condition, compare_conditions


class TestUtils:
    @pytest.fixture
    def source(self):
        return {
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
    def conditions(self):
        return [
            ContextualRule(
                name="Rule 1",
                contextual_rules=[{"resource": "res1"}],
                context={"message": "Matched Rule 1"}
            ),
            ContextualRule(
                name="Rule 2",
                contextual_rules=[{"resource": "res1", "attributes": {"attr1": "valor1"}}],
                context={"message": "Matched Rule 2"}
            ),
            ContextualRule(
                name="Rule 3",
                contextual_rules=[{"resource": "res1", "attributes": {"attr1": "valor1"}, "tags": ["tag1"]}],
                context={"message": "Matched Rule 3"}
            ),
            ContextualRule(
                name="Rule 4",
                contextual_rules=[{"createTime": {"$gt": datetime.now()}}],
                context={"message": "Matched Rule 4"}
            ),
            ContextualRule(
                name="Rule 5",
                contextual_rules=[{"try": "try1"}, {"resource": "res1", "event": "event1"}, {"try": "try2"}],
                context={"message": "Matched Rule 5"}
            ),
            ContextualRule(
                name="Rule 6",
                contextual_rules=[{"resource": "res2"}],
                context={"message": "Matched Rule 6"}
            ),
            ContextualRule(
                name="Rule 7",
                contextual_rules=[{"attributes": {"attr1": "valor2"}}],
                context={"message": "Matched Rule 7"}
            ),
            ContextualRule(
                name="Rule 8",
                contextual_rules=[{"tags": ["tag3"]}],
                context={"message": "Matched Rule 8"}
            )
        ]

    @pytest.fixture
    def conditions_with_sets(self):
        return [
            ContextualRule(
                name="Rule 1",
                contextual_rules=[{"resource": "res1"}],
                context={"message": "Matched Rule 1"}
            ),
            ContextualRule(
                name="Rule 2",
                contextual_rules=[{"resource": "res1", "attributes": {"attr1": "valor1"}}],
                context={"message": "Matched Rule 2"}
            ),
            ContextualRule(
                name="Rule 3",
                contextual_rules=[{"resource": "res1", "attributes": {"attr1": "valor1"}, "tags": ["tag1"]}],
                context={"tags": {"tag1", "tag2"}}
            )
        ]

    @pytest.fixture
    def conditions_with_different_attributes(self):
        return [
            ContextualRule(
                name="Rule 1",
                contextual_rules=[{"resource": "res1"}],
                context={"message": "Matched Rule 1"}
            ),
            ContextualRule(
                name="Rule 2",
                contextual_rules=[{"resource": "res1", "attributes": {"attr1": "valor1"}}],
                context={"message": "Matched Rule 2"}
            ),
            ContextualRule(
                name="Rule 3",
                contextual_rules=[{"resource": "res1", "attributes": {"attr1": "valor1"}}, {"tags": ["tag1"]}],
                context={"tags": {"tag1", "tag2"}}
            )
        ]

    @pytest.fixture
    def conditions_with_different_attributes_changed(self):
        return [
            ContextualRule(
                name="Rule 1",
                contextual_rules=[{"resource": "res1"}],
                context={"message": "Matched Rule 1"}
            ),
            ContextualRule(
                name="Rule 2",
                contextual_rules=[{"resource": "res1", "attributes": {"attr1": "valor1"}}],
                context={"message": "Matched Rule 2"}
            ),
            ContextualRule(
                name="Rule 3",
                contextual_rules=[{"tags": ["tag1"]}, {"resource": "res1", "attributes": {"attr1": "valor1"}}],
                context={"tags": {"tag1", "tag2"}}
            )
        ]

    @pytest.fixture
    def conditions_with_different_dicts(self):
        return [
            ContextualRule(
                name="Rule 1",
                contextual_rules=[{"resource": "res1"}],
                context={"message": "Matched Rule 1"}
            ),
            ContextualRule(
                name="Rule 2",
                contextual_rules=[{"resource": "res1", "attributes": {"attr1": "valor1"}}],
                context={"message": "Matched Rule 2", "tags": {"tag1": "one", "tag2": "two"}}
            ),
            ContextualRule(
                name="Rule 3",
                contextual_rules=[{"resource": "res1", "attributes": {"attr1": "valor1"}, "tags": ["tag1"]}],
                context={"tags": {"tag1": "value1", "tag2": "value2", "tag3": "value 3", "tag4": "value4"}}
            )
        ]

    @pytest.fixture
    def conditions_with_lists(self):
        return [
            ContextualRule(
                name="Rule 1",
                contextual_rules=[{"resource": "res1"}],
                context={"message": "Matched Rule 1"}
            ),
            ContextualRule(
                name="Rule 2",
                contextual_rules=[{"resource": "res1", "attributes": {"attr1": "valor1"}}],
                context={"message": "Matched Rule 2", "tags": ["tag1"]}
            ),
            ContextualRule(
                name="Rule 3",
                contextual_rules=[{"resource": "res1", "attributes": {"attr1": "valor1"}, "tags": ["tag1"]}],
                context={"message": "Matched Rule 3"}
            )
        ]

    @pytest.fixture
    def conditions_with_lists_in_different_rules(self):
        return [
            ContextualRule(
                name="Rule 1",
                contextual_rules=[{"resource": "res1"}],
                context={"message": "Matched Rule 1"}
            ),
            ContextualRule(
                name="Rule 2",
                contextual_rules=[{"resource": "res1", "attributes": {"attr1": "valor1"}}],
                context={"message": "Matched Rule 2", "tags": ["tag1"]}
            ),
            ContextualRule(
                name="Rule 3",
                contextual_rules=[{"resource": "res1", "attributes": {"attr1": "valor1"}, "tags": ["tag1"]}],
                context={"message": "Matched Rule 3", "tags": ["tag1", "tag2", "tag3"]}
            )
        ]

    @pytest.fixture
    def conditions_with_string_and_int(self):
        return [
            ContextualRule(
                name="Rule 1",
                contextual_rules=[{"resource": "res1"}],
                context={"message": "Matched Rule 1", "level": "critical"}
            ),
            ContextualRule(
                name="Rule 2",
                contextual_rules=[{"resource": "res1", "attributes": {"attr1": "valor1"}}],
                context={"message": "Matched Rule 2", "tags": ["tag1"]}
            ),
            ContextualRule(
                name="Rule 3",
                contextual_rules=[{"resource": "res1", "attributes": {"attr1": "valor1"}, "tags": ["tag1"]}],
                context={"message": "Matched Rule 3", "priority": 1},
                last_check=True
            )
        ]

    def test_compare_conditions_with_sets(self, source, conditions_with_sets):
        assert compare_conditions(source, conditions_with_sets) == \
               {"message": "Matched Rule 1", "tags": {"tag1", "tag2"}}

    def test_compare_conditions_with_different_attributes(self, source, conditions_with_different_attributes):
        assert compare_conditions(source, conditions_with_different_attributes) == \
               {"message": "Matched Rule 1", "tags": {"tag1", "tag2"}}

    def test_compare_conditions_with_different_attributes_changed(self, source,
                                                                  conditions_with_different_attributes_changed):
        assert compare_conditions(source, conditions_with_different_attributes_changed) == \
               {"message": "Matched Rule 1", "tags": {"tag1", "tag2"}}

    def test_compare_conditions_with_lists(self, source, conditions_with_lists):
        assert compare_conditions(source, conditions_with_lists) == {"message": "Matched Rule 1", "tags": ["tag1"]}

    def test_compare_conditions_with_strings_and_int(self, source, conditions_with_string_and_int):
        assert compare_conditions(source, conditions_with_string_and_int) == \
               {"message": "Matched Rule 1", "level": "critical", "priority": 1, "tags": ["tag1"]}

    def test_compare_conditions_with_lists_in_different_rules(self, source, conditions_with_lists_in_different_rules):
        assert compare_conditions(source, conditions_with_lists_in_different_rules) == \
               {"message": "Matched Rule 1", "tags": ["tag1"]}

    def test_compare_conditions_with_different_dicts(self, source, conditions_with_different_dicts):
        assert compare_conditions(source, conditions_with_different_dicts) == \
               {"message": "Matched Rule 1", "tags": {"tag1": "one", "tag2": "two", "tag3": "value 3", "tag4": "value4"}
                }

    def test_compare_conditions(self, source, conditions):
        assert compare_conditions(source, conditions) == {"message": "Matched Rule 1"}

    def test_compare_condition(self, source, conditions):
        assert compare_condition(source, conditions[0]) == {"message": "Matched Rule 1"}
        assert compare_condition(source, conditions[1]) == {"message": "Matched Rule 2"}
        assert compare_condition(source, conditions[2]) == {"message": "Matched Rule 3"}
        assert compare_condition(source, conditions[3]) == {}
        assert compare_condition(source, conditions[4]) == {"message": "Matched Rule 5"}
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
