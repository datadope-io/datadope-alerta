import logging

from flask import request, current_app, g, jsonify, url_for
from flask_cors import cross_origin

from alerta.auth.decorators import permission
from alerta.exceptions import ApiError
from alerta.models.alert import Alert
from alerta.models.enums import Scope
from alerta.models.metrics import Timer, timer
from alerta.utils.api import assign_customer
from alerta.utils.audit import write_audit_trail
from alerta.utils.response import jsonp
from alerta.app import db

from . import iom_api

logger = logging.getLogger(__name__)


receive_timer = Timer('alerts', 'received_async', 'Received async alerts',
                      'Total time and number of async received alerts')



@iom_api.route('/async/alert', methods=['OPTIONS', 'POST'])
@cross_origin()
@permission(Scope.write_alerts)
@timer(receive_timer)
@jsonp
def receive():
    logger.debug("Received an async request to create an alert")
    # Check request
    try:
        alert = Alert.parse(request.json)
    except ValueError as e:
        raise ApiError(str(e), 400)

    alert.customer = assign_customer(wanted=alert.customer)

    # To support remote_ip plugin
    remote_addr = next(iter(request.access_route), request.remote_addr)
    environ = {'REMOTE_ADDR': remote_addr}

    from iometrics_alerta.bgtasks.async_alert_task import async_receive
    # bg_task_id = async_receive.apply_async(kwargs=dict(alert=alert.serialize, user=g.login))
    task = async_receive.apply_async(kwargs=dict(alert_dict=alert.serialize,
                                                 user=g.login,
                                                 customers=g.get('customers'),
                                                 scopes=g.scopes,
                                                 request_environ=environ),
                                     queue=current_app.config.get('ASYNC_ALERT_TASK_QUEUE'))
    logger.info("Scheduled background task to process a new alert: %s", task.id)
    db.backend_async_alert.create(task.id)
    write_audit_trail.send(current_app._get_current_object(),  # noqa
                           event='alert-received-async', message=alert.text, user=g.login,
                           customers=g.customers, scopes=g.scopes, resource_id=task.id,
                           type='alert', request=request)
    response = jsonify({'task_id': task.id, "status": "waiting"})
    response.status = 202
    url = url_for(endpoint='iom_api.get_alert_status', bg_task_id=task.id,
                  _external=True)
    response.headers['Content-Location'] = url
    return response

@iom_api.route('/async/alert/<bg_task_id>', methods=['OPTIONS', 'GET'])
@cross_origin()
@permission(Scope.read_alerts)
@jsonp
def get_alert_status(bg_task_id):
    try:
        info = db.backend_async_alert.get_alert_id(bg_task_id)
    except KeyError:
        logger.warning("Requested status of a non-existing async task '%s'", bg_task_id)
        raise ApiError(f"'{bg_task_id}' task not found", code=404)
    if not info:
        return jsonify(task_id=bg_task_id, status="waiting"), 200
    alert_id = None
    errors = None
    if isinstance(info, str):
        alert_id = info
    else:
        errors = info

    if errors:
        errors['task_id'] = bg_task_id
        return jsonify(errors), 200
    else:
        url = url_for(endpoint='api.get_alert', alert_id=alert_id,
                      _external=True)
        response = jsonify({'task_id': bg_task_id, "status": "ok", "alert_id": alert_id})
        response.status = 200
        response.headers['Location'] = url
        return response
