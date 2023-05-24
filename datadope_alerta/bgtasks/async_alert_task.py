from typing import Optional

from flask import current_app, g, request

from alerta.app import db
from alerta.exceptions import RejectException, RateLimit, BlackoutPeriod, ForwardingLoop, AlertaException, ApiError, \
    HeartbeatReceived
from alerta.models.alert import Alert
from alerta.utils.audit import write_audit_trail
from alerta.utils.api import process_alert
from datadope_alerta import thread_local
from datadope_alerta.plugins import getLogger
from datadope_alerta.bgtasks import celery


logger = getLogger(__name__)

def jsonify(**kwargs):
    return kwargs


@celery.task(bind=True, ignore_result=True)
def async_receive(self, alert_dict: dict, user: str, customers: Optional[list], scopes,
                  request_environ: dict):
    logger.debug("Creating new alert asynchronously")
    alert = Alert.parse(alert_dict)
    g.login = user
    g.customers = customers
    g.scopes = scopes
    try:
        with current_app.test_request_context(environ_base=request_environ):
            response, code = _create_alert(alert)
    except ApiError as e:
        response = {x: y for x, y in {
            "status": "error",
            "message": e.message,
            "errors": e.errors
        }.items() if y is not None}
        code = e.code or 500

    alert_id = None
    errors = None
    if code == 201:
        alert_id = response["id"]
        thread_local.alert_id = alert_id
        logger.info("Created alert asynchronously")
    else:
        response["code"] = code
        errors = response
        logger.info("Error creating alert asynchronously: %s", errors)

    db.backend_async_alert.update(self.request.id, alert_id=alert_id, errors=errors)


def _create_alert(alert: Alert):
    sender = current_app._get_current_object()  # noqa
    def audit_trail_alert(event: str):
        write_audit_trail.send(sender, event=event, message=alert.text,
                               user=g.login, customers=g.customers, scopes=g.scopes, resource_id=alert.id,
                               type='alert', request=request)

    try:
        alert = process_alert(alert)
    except RejectException as e:
        audit_trail_alert(event='alert-rejected')
        raise ApiError(str(e), 403)
    except RateLimit as e:
        audit_trail_alert(event='alert-rate-limited')
        return jsonify(status='error', message=str(e), id=alert.id), 429
    except HeartbeatReceived as heartbeat:
        audit_trail_alert(event='alert-heartbeat')
        return jsonify(status='ok', message=str(heartbeat), id=heartbeat.id), 202
    except BlackoutPeriod as e:
        audit_trail_alert(event='alert-blackout')
        return jsonify(status='ok', message=str(e), id=alert.id), 202
    except ForwardingLoop as e:
        return jsonify(status='ok', message=str(e)), 202
    except AlertaException as e:
        raise ApiError(e.message, code=e.code, errors=e.errors)
    except Exception as e:
        raise ApiError(str(e), 500)

    write_audit_trail.send(sender, event='alert-received', message=alert.text,
                           user=g.login, customers=g.customers, scopes=g.scopes, resource_id=alert.id,
                           type='alert', request=request)

    if alert:
        return jsonify(status='ok', id=alert.id), 201
    else:
        raise ApiError('insert or update of received alert failed', 500)
