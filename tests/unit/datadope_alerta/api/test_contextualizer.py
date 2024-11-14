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

    def test_add_rule(self, get_app, set_up_api):
        """
            GIVEN an api call asking to add a new rule.
            WHEN it does not exist on the database.
            THEN assert that the response contains the new rule
                 containing the auto-incremental id obtained
                 from the database.
        """
        with pytest.app.test_request_context(json={
            'name': 'testing_rule',
            'contextual_rules': {'event': 'TestEvent'},
            'context': {'event': 'This is a testing event'},
            'priority': 2000,
            'last_check': True
        }):
            response = set_up_api.create_rule()

        assert 'id' in list(response.json.keys())
        assert response.json['id'] is not None

    def test_add_rule_fails(self, get_app, set_up_api):
        """
            GIVEN an api call asking to add a new rule.
            WHEN it has a name that is already stored on the database.
            THEN assert that an error will be raised.
        """
        with pytest.app.test_request_context(json={
            'name': 'testing_rule',
            'contextual_rules': {'event': 'TestEvent'},
            'context': {'event': 'This is a testing event'},
            'priority': 2000,
            'last_check': True
        }):
            with pytest.raises(Exception):
                set_up_api.create_rule()

        """
            GIVEN an api call asking to add a new rule.
            WHEN the request does not contain a rule on the body.
            THEN assert that an error will be raised.
        """
        with pytest.app.test_request_context(json={}):
            with pytest.raises(Exception):
                set_up_api.create_rule()

    def test_read_rule(self, get_request, set_up_api):
        """
        GIVEN an api call asking for a specific rule.
        WHEN it exists on the database.
        THEN assert that the response is that of a dict containing all
             the requested information.
        """
        response = set_up_api.read_rule('testing_rule')

        assert ('append_lists', 'context', 'contextual_rules', 'id', 'last_check', 'name', 'priority') == tuple(response.json.keys())

    def test_read_rule_fails(self, get_request, set_up_api):
        """
            GIVEN an api call asking for a specific rule.
            WHEN it does not exist on the database.
            THEN assert that an empty list will be returned
                 as there is no rule matching the given name.
        """
        resp = set_up_api.read_rule('non_existent_rule')
        assert resp.json == []

    def test_read_all_rules(self, get_request, set_up_api):
        """
            GIVEN an api call asking for all the registered rules
            THEN assert that the response is a paginated list of
                 elements.
        """
        response = set_up_api.read_all_rules()
        assert isinstance(response.json, list)
        assert len(response.json) >= 0

    def test_update_rule(self, get_request, set_up_api):
        """
            GIVEN an api call asking to update an existing rule.
            THEN assert that the rule has changed.
        """
        prev = set_up_api.read_rule('testing_rule')
        with pytest.app.test_request_context(json={
            'name': 'testing_rule',
            'contextual_rules': {'event': 'this has changed'},
            'context': {'event': 'this has changedt'},
            'priority': 2000,
            'last_check': True
        }):
            response = set_up_api.update_rule(rule_id=prev.json['id'])

        assert prev.json != response.json

    def test_update_rule_fails(self, get_request, set_up_api):
        """
            GIVEN an api call asking to update a non-existing rule.
            THEN assert that the response notifies the error with the given ID.
        """
        with pytest.app.test_request_context(json={}):
            response = set_up_api.update_rule(rule_id=10000)
        assert response.json == "Error: no rule matching the given ID"

    def test_delete_rule(self, get_request, set_up_api):
        """
            GIVEN an api call asking for deleting an existing rule.
            THEN assert that the rule has been deleted.
        """
        rule = ContextualRule.from_dict(set_up_api.read_rule('testing_rule').json)
        response = set_up_api.delete_rule(rule_id=rule.id)
        assert response.json == rule.__dict__

    def test_delete_rule_fails(self, get_request, set_up_api):
        """
            GIVEN an api call asking to delete a non-existing rule.
            THEN assert that the response notifies the error with the given ID.
        """
        response = set_up_api.delete_rule(rule_id=10000)
        assert response.json == "Error: no rule matching the given ID"
