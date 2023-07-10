from alerta.auth.decorators import permission
from alerta.models.enums import Scope
from alerta.utils.response import jsonp
from flask import jsonify, request
from flask_cors import cross_origin

from . import iom_api
from ..backend.flexiblededup.models.alert_dependency import AlertDependency


# noinspection PyProtectedMember,SpellCheckingInspection
class AlertDependenciesApi:

    @staticmethod
    @iom_api.route('/alert_dependency', methods=['OPTIONS', 'POST'])
    @cross_origin()
    @permission(Scope.write_alerts)
    @jsonp
    def create_alert_dependency():
        form = request.json
        alert_dependency = AlertDependency.from_dict(form)
        resp = alert_dependency.add_to_db(alert_dependency)
        response = jsonify(resp.__dict__)
        response.status = 201
        return response

    @staticmethod
    @iom_api.route('/alert_dependency/<resource>/<event>', methods=['OPTIONS', 'GET'])
    @cross_origin()
    @permission(Scope.read_alerts)
    @jsonp
    def read_alert_dependency(resource, event):
        resp = AlertDependency.one_from_db(resource=resource, event=event)
        return jsonify(resp.__dict__) if resp else jsonify([])

    @staticmethod
    @iom_api.route('/alert_dependency', methods=['OPTIONS', 'GET'])
    @cross_origin()
    @permission(Scope.read_alerts)
    @jsonp
    def read_all_alert_dependencies(limit=50, offset=0):
        limit = request.args.get('limit', limit)
        offset = request.args.get('offset', offset)
        resp = AlertDependency.all_from_db(limit=limit, offset=offset)
        return jsonify(resp)

    @staticmethod
    @iom_api.route('/alert_dependency/<resource>/<event>', methods=['OPTIONS', 'PUT'])
    @cross_origin()
    @permission(Scope.write_alerts)
    @jsonp
    def update_alert_dependency(resource, event):
        form = request.json
        alert_dependency = AlertDependency.from_dict(form)
        alert_dependency.resource = resource
        alert_dependency.event = event
        resp = alert_dependency.update_from_db(alert_dependency)
        return jsonify(resp.__dict__)

    @staticmethod
    @iom_api.route('/alert_dependency/<resource>/<event>', methods=['OPTIONS', 'DELETE'])
    @cross_origin()
    @permission(Scope.write_alerts)
    @jsonp
    def delete_alert_dependency(resource, event):
        resp = AlertDependency.clear(resource=resource, event=event)
        return jsonify(resp)
