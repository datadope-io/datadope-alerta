import pytest

from datadope_alerta.api.contextualizer import ContextualizerAPI
from datadope_alerta.backend.flexiblededup.models.rules import ContextualRule
from datadope_alerta.backend.flexiblededup.specific import SpecificBackend


# noinspection SpellCheckingInspection
def _create_contextual_rule(name: str, contextual_rules: dict, context: dict, priority: int, last_check: bool):
    return ContextualRule.from_dict({
        'name': name,
        'contextual_rules': contextual_rules,
        'context': context,
        'priority': priority,
        'last_check': last_check
    })


# noinspection PyProtectedMember,SpellCheckingInspection
class TestsContextualizer:

    @pytest.fixture()
    def set_up_api(self):
        return ContextualizerAPI()

    @pytest.fixture()
    def set_up_backend(self):
        return SpecificBackend.instance

    def test_read_rule(self, get_request, set_up_api, set_up_backend):
        """
        GIVEN an api call asking for a specific rule.
        WHEN it exists on the database.
        THEN assert that the response is that of a dict containing all
             the required information.
        """
        set_up_backend.create_contextual_rule(
            _create_contextual_rule('rule1', {'event': 'NodeDown'}, {'event': 'A data node is down'}, 2000, True))
        response = set_up_api.read_rule('rule1')

        assert ('context', 'contextual_rules', 'id', 'last_check', 'name', 'priority') == tuple(response.json.keys())

    def test_read_rule_fails(self, get_request, set_up_api):
        """
            GIVEN an api call asking for a specific rule.
            WHEN it does not exist on the database.
            THEN assert that an AttributeError will be raised,
                 as there is no rule matching that name.
        """
        resp = set_up_api.read_rule('rule2')
        assert isinstance(resp.json, list)
        assert len(resp.json) == 0

    def test_read_all_rules(self, get_request, set_up_api):
        """
            GIVEN an api call asking for all the registered rules
            THEN assert that the response is a paginated list of
                 elements.
        """
        response = set_up_api.read_all_rules()
        assert isinstance(response.json, list)

    def test_add_rule(self, get_request_with_body, set_up_api):
        """
            GIVEN an api call asking to add a new rule.
            WHEN it does not exist on the database.
            THEN assert that the response contains the new rule
                 containing the auto-incremental id obtained
                 from the database.
        """
        response = set_up_api.create_rule()
        assert 'id' in list(response.json.keys())
        assert response.json['id'] is not None

    def test_add_rule_fails(self, get_request, set_up_api):
        """
            GIVEN an api call asking to add a new rule.
            WHEN it has a name that is already stored on the database.
            THEN assert that an error will be raised.
        """
        with pytest.raises(Exception):
            set_up_api.create_rule()
