from flask import jsonify
from flask_cors import cross_origin

from alerta.auth.decorators import permission
from alerta.models.enums import Scope
from alerta.utils.response import jsonp
from alerta.app import db

from . import iom_api
from ..backend.flexiblededup.models.alerters import AlerterOperationData


@iom_api.route('/alert/<alert_id>/alerters', methods=['OPTIONS', 'GET'])
@cross_origin()
@permission(Scope.read_alerts)
@jsonp
def get_alerter_data(alert_id):
    # TODO: Mover las queries a métodos del backend
    query = """
        SELECT * FROM alerter_data WHERE alert_id=%(alert_id)s
    """
    resp = db._fetchall(query=query, vars={'alert_id': alert_id}, limit=100)
    operation_data = {}
    for record in resp:
        operation_data.setdefault(record.alerter, []).append(AlerterOperationData.from_record(record).__dict__)
    query_status = """
        SELECT alerter, status FROM alerter_status WHERE alert_id=%(alert_id)s
    """
    resp = db._fetchall(query=query_status, vars={'alert_id': alert_id}, limit=100)
    status_data = {x.alerter: x.status for x in resp}
    data = {}
    for alerter, status in status_data.items():
        data[alerter] = {
            "status": status,
            "data": operation_data.get(alerter)
        }
    return jsonify(data)
