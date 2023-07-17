from flask import jsonify, request
from flask_cors import cross_origin

from alerta.auth.decorators import permission
from alerta.models.enums import Scope
from alerta.utils.response import jsonp

from . import iom_api
from ..backend.flexiblededup.models.rules import ContextualRule


# noinspection PyProtectedMember,SpellCheckingInspection
class ContextualizerAPI:

    @staticmethod
    @iom_api.route('/alert_context/rules', methods=['OPTIONS', 'POST'])
    @cross_origin()
    @permission(Scope.write_alerts)
    @jsonp
    def create_rule():
        form = request.json
        rule = ContextualRule.from_dict(form)
        resp = rule.store()
        response = jsonify(resp.__dict__)
        response.status = 201
        return response

    @staticmethod
    @iom_api.route('/alert_context/rules/<name>', methods=['OPTIONS', 'GET'])
    @cross_origin()
    @permission(Scope.read_alerts)
    @jsonp
    def read_rule(name):
        resp = ContextualRule.one_from_db(name=name)
        return jsonify(resp.__dict__) if resp else jsonify([])

    @staticmethod
    @iom_api.route('/alert_context/rules', methods=['OPTIONS', 'GET'])
    @cross_origin()
    @permission(Scope.read_alerts)
    @jsonp
    def read_all_rules(limit=50, offset=0):
        limit = request.args.get('limit', limit)
        offset = request.args.get('offset', offset)
        resp = ContextualRule.all_from_db(limit=limit, offset=offset)
        return jsonify(resp)

    @staticmethod
    @iom_api.route('/alert_context/rules/<rule_id>', methods=['OPTIONS', 'PUT'])
    @cross_origin()
    @permission(Scope.write_alerts)
    @jsonp
    def update_rule(rule_id):
        form = request.json
        rule = ContextualRule.from_dict(form)
        rule.id = rule_id
        resp = rule.store()
        return jsonify(resp.__dict__ if resp else 'Error: no rule matching the given ID')

    @staticmethod
    @iom_api.route('/alert_context/rules/<rule_id>', methods=['OPTIONS', 'DELETE'])
    @cross_origin()
    @permission(Scope.write_alerts)
    @jsonp
    def delete_rule(rule_id):
        resp = ContextualRule.clear(rule_id)
        return jsonify(resp.__dict__ if resp else 'Error: no rule matching the given ID')
