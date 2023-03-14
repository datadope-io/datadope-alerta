import json
import logging
import os
import threading
from datetime import datetime, date
from enum import Enum

import pytz

from flask import current_app, render_template_string  # noqa
from psycopg2.extras import register_composite

from alerta.app import alarm_model
from alerta.database.backends.postgres import Backend as PGBackend, Record, register_adapter, Json, HistoryAdapter
from alerta.models.enums import Status, Severity
from alerta.utils.format import DateTime

from .specific import SpecificBackend

ATTRIBUTE_DEDUPLICATION = 'deduplication'
ATTRIBUTE_DEDUPLICATION_TYPE = 'deduplicationType'
ATTRIBUTE_ORIGINAL_ID = 'tempOriginalAlertId'  # If alert is deduplicated, stores the original id.
ATTRIBUTE_ORIGINAL_VALUE = 'tempOriginalValue'  # temp attribute => not stored

CONFIG_DEFAULT_DEDUPLICATION_TYPE = 'DEFAULT_DEDUPLICATION_TYPE'
CONFIG_DEFAULT_DEDUPLICATION_TEMPLATE = 'DEFAULT_DEDUPLICATION_TEMPLATE'

logger = logging.getLogger(__name__)


class DeduplicationType(str, Enum):
    Both = 'both'
    ByAttribute = 'attribute'

    @classmethod
    def _missing_(cls, value):
        return cls.Both


class JsonWithDatetime(Json):

    @staticmethod
    def json_serial(obj):
        """JSON serializer for objects not serializable by default json code"""
        if isinstance(obj, (datetime, date)):
            return DateTime.iso8601(obj.astimezone(pytz.utc))
        raise TypeError(f"Type {type(obj)} not serializable")

    def dumps(self, obj):
        return json.dumps(obj, default=self.json_serial)


class Backend(PGBackend):

    def __init__(self, app=None):
        self.uri = None
        self.dbname = None
        self.backend_alerters = None
        super().__init__(app=app)

    @classmethod
    def render_value(cls, value, **kwargs):
        if isinstance(value, dict):
            result = {}
            for k, v in value.items():
                result[k] = cls.render_value(v, **kwargs)
            return result
        elif isinstance(value, list):
            result = []
            for el in value:
                result.append(cls.render_value(el, **kwargs))
            return result
        elif isinstance(value, str):
            return render_template_string(value, **kwargs)
        else:
            return value

    @classmethod
    def _get_deduplication_value(cls, alert):
        deduplication = alert.attributes.get(ATTRIBUTE_DEDUPLICATION)
        if deduplication is None:
            template = current_app.config.get(CONFIG_DEFAULT_DEDUPLICATION_TEMPLATE)
            if template:
                try:
                    deduplication = cls.render_value(template, alert=alert)
                except Exception as e:
                    current_app.logger.warning("Wrong template for %s: '%s': %s",
                                               CONFIG_DEFAULT_DEDUPLICATION_TEMPLATE,
                                               template, e)
                    deduplication = None
        return deduplication

    def create_engine(self, app, uri, dbname=None, raise_on_error=True):
        self.uri = f"postgresql://{uri.split('://')[1]}"
        self.dbname = dbname

        lock = threading.Lock()
        with lock:
            conn = self.connect()
            schema_file = os.path.abspath(os.path.join(os.path.dirname(__file__), 'schema.sql'))
            with open(schema_file, 'r') as f:
                try:
                    conn.cursor().execute(f.read())
                    conn.commit()
                except Exception as e:
                    if raise_on_error:
                        raise
                    app.logger.warning(e)

        register_adapter(dict, Json)
        register_adapter(datetime, self._adapt_datetime)
        register_composite(
            'history',
            conn,
            globally=True
        )
        from alerta.models.alert import History
        register_adapter(History, HistoryAdapter)
        register_adapter(dict, JsonWithDatetime)
        self.backend_alerters = SpecificBackend(self)

    def create_alert(self, alert):
        deduplication = alert.attributes.get(ATTRIBUTE_DEDUPLICATION)
        if deduplication:
            alert.value = alert.attributes.pop(ATTRIBUTE_ORIGINAL_VALUE, None) or alert.value
        return super(Backend, self).create_alert(alert)

    # noinspection PyShadowingBuiltins
    def set_alert(self, id, severity, status, tags, attributes, timeout, previous_severity, update_time, history=None):
        update = """
            UPDATE alerts
               SET severity=%(severity)s, status=%(status)s, tags=ARRAY(SELECT DISTINCT UNNEST(tags || %(tags)s)),
                   attributes=attributes || %(attributes)s, timeout=%(timeout)s, 
                   previous_severity=%(previous_severity)s,
                   update_time=%(update_time)s, history=(%(change)s || history)[1:{limit}]
             WHERE id=%(id)s OR id LIKE %(like_id)s
         RETURNING *
        """.format(limit=current_app.config['HISTORY_LIMIT'])
        return self._updateone(update, {'id': id, 'like_id': id + '%', 'severity': severity, 'status': status,
                                        'tags': tags, 'attributes': attributes, 'timeout': timeout,
                                        'previous_severity': previous_severity, 'update_time': update_time,
                                        'change': history}, returning=True)

    @staticmethod
    def _deduplication_filter(deduplication_type, deduplication):
        if deduplication_type == DeduplicationType.ByAttribute and not deduplication:
            # Deduplication only by attribute but no attribute is provided => alert can not deduplicate
            dedup_filter = None
        elif deduplication_type == DeduplicationType.ByAttribute:
            # Deduplicate only by attribute
            dedup_filter = "attributes->>'{deduplication_attr}'='{deduplication}'"
        elif not deduplication:
            # Deduplicate only by resource/event
            dedup_filter = 'resource=%(resource)s AND event=%(event)s'
        else:
            # Deduplicate by resource/event or attribute
            dedup_filter = "((resource=%(resource)s AND event=%(event)s) " \
                           "OR attributes->>'{deduplication_attr}'='{deduplication}')"
        if dedup_filter:
            dedup_filter = dedup_filter.format(deduplication_attr=ATTRIBUTE_DEDUPLICATION,
                                               deduplication=deduplication)
        return dedup_filter

    def is_duplicate(self, alert):
        deduplication_type = DeduplicationType(alert.attributes.get(
            ATTRIBUTE_DEDUPLICATION_TYPE, current_app.config.get(CONFIG_DEFAULT_DEDUPLICATION_TYPE, '')).lower())
        deduplication = self._get_deduplication_value(alert)
        if deduplication:
            alert.attributes[ATTRIBUTE_DEDUPLICATION] = deduplication
            alert.attributes[ATTRIBUTE_ORIGINAL_VALUE] = alert.value
            alert.value = f"{alert.resource}/{alert.event}/{alert.value if alert.value else '#NO VALUE#'}"

        dedup_filter = self._deduplication_filter(deduplication_type, deduplication)
        if not dedup_filter:
            return
        select = """
            SELECT * FROM alerts
             WHERE environment=%(environment)s
               AND {dedup_filter}
               AND {customer}
          ORDER BY CASE WHEN (severity in ('normal', 'ok', 'cleared')) THEN 10
                        ELSE 0
                   END ASC, update_time DESC
            """.format(customer='customer=%(customer)s' if alert.customer else 'customer IS NULL',
                       dedup_filter=dedup_filter)
        original = self._fetchone(select, vars(alert))
        if original:
            if original.severity != alert.severity:
                # Only deduplicate if severity is the same. If not the same => correlate
                return None
            # If deduplicated by attribute deduplication, resource and event may be different but history is only
            # created if value or status change. So including resource and event in value forces to create history
            # if value has not changed but resource or event have.
            alert.attributes[ATTRIBUTE_ORIGINAL_ID] = original.id
            alert.attributes.pop(ATTRIBUTE_DEDUPLICATION, None)
            logger.debug("[DEDUPLICATION] Deduplicating alert '%s' -> '%s'", alert.id, original.id)
        return original

    def dedup_alert(self, alert, history):
        """
        Take into account attributes.deduplication. In this case, resource, event and severity may change (they can't
        change in the standard deduplication mechanism).
        IMPORTANT: Trend will change if severity changes but cannot be calculated without modifying alerta logic.
        """
        alert.value = alert.attributes.pop(ATTRIBUTE_ORIGINAL_VALUE, None) or alert.value
        original_id = alert.attributes.pop(ATTRIBUTE_ORIGINAL_ID)
        if original_id:
            alert.history = history
            update = """
                UPDATE alerts
                   SET resource=%(resource)s, event=%(event)s, previous_severity=severity, severity=%(severity)s,
                       status=%(status)s, service=%(service)s, value=%(value)s, text=%(text)s,
                       timeout=%(timeout)s, raw_data=%(raw_data)s, repeat=%(repeat)s,
                       last_receive_id=%(last_receive_id)s, last_receive_time=%(last_receive_time)s,
                       tags=ARRAY(SELECT DISTINCT UNNEST(tags || %(tags)s)), attributes=attributes || %(attributes)s,
                       duplicate_count=duplicate_count + 1, {update_time}, history=(%(history)s || history)[1:{limit}]
                 WHERE id='{original_id}'
             RETURNING *
            """.format(
                limit=current_app.config['HISTORY_LIMIT'],
                update_time='update_time=%(update_time)s' if alert.update_time else 'update_time=update_time',
                original_id=original_id
            )
            return self._updateone(update, vars(alert), returning=True)
        logger.error("Deduplicating alert '%s' without '%s' attribute", alert.id, ATTRIBUTE_ORIGINAL_ID)
        return alert  # should not happen

    def is_correlated(self, alert):
        deduplication_type = DeduplicationType(alert.attributes.get(
            ATTRIBUTE_DEDUPLICATION_TYPE, current_app.config.get(CONFIG_DEFAULT_DEDUPLICATION_TYPE, '')).lower())
        deduplication = self._get_deduplication_value(alert)
        dedup_filter = self._deduplication_filter(deduplication_type, deduplication)
        if not dedup_filter:
            dedup_filter = 'false'
        select = """
            SELECT * FROM alerts
             WHERE environment=%(environment)s
               AND ({dedup_filter} OR (resource=%(resource)s AND event!=%(event)s AND %(event)s=ANY(correlate)))
               AND {customer}
          ORDER BY CASE WHEN (severity in ('normal', 'ok', 'cleared')) THEN 10
                        ELSE 0
                   END ASC, update_time DESC
            """.format(customer='customer=%(customer)s' if alert.customer else 'customer IS NULL',
                       dedup_filter=dedup_filter)
        original = self._fetchone(select, vars(alert))
        if original and original.status in (Status.Closed, Status.Expired) and alert.severity not in (
                Severity.Normal, Severity.Ok, Severity.Cleared):
            # Alerts are not reopened. A new one is created
            logger.debug("[CORRELATION] Alert '%s' severity changes from '%s' to '%s'. Creating new alert '%s'",
                         original.id, original.severity, alert.severity, alert.id)
            return None
        if original:
            logger.debug("[CORRELATION] Alert '%s' severity changes from '%s' to '%s'. Correlating received alert '%s'",
                         original.id, original.severity, alert.severity, alert.id)
            alert.attributes[ATTRIBUTE_ORIGINAL_ID] = original.id
            alert.attributes.pop(ATTRIBUTE_DEDUPLICATION, None)
        return original

    def correlate_alert(self, alert, history):
        alert.value = alert.attributes.pop(ATTRIBUTE_ORIGINAL_VALUE, None) or alert.value
        original_id = alert.attributes.pop(ATTRIBUTE_ORIGINAL_ID)
        if original_id:
            alert.history = history
            update = """
                UPDATE alerts
                   SET event=%(event)s, severity=%(severity)s, status=%(status)s, service=%(service)s, value=%(value)s,
                       text=%(text)s, create_time=%(create_time)s, timeout=%(timeout)s, raw_data=%(raw_data)s,
                       duplicate_count=%(duplicate_count)s, repeat=%(repeat)s, previous_severity=%(previous_severity)s,
                       trend_indication=%(trend_indication)s, receive_time=%(receive_time)s, 
                       last_receive_id=%(last_receive_id)s, last_receive_time=%(last_receive_time)s, 
                       tags=ARRAY(SELECT DISTINCT UNNEST(tags || %(tags)s)), attributes=attributes || %(attributes)s, 
                       {update_time}, history=(%(history)s || history)[1:{limit}]
                 WHERE id='{original_id}'
             RETURNING *
            """.format(
                limit=current_app.config['HISTORY_LIMIT'],
                update_time='update_time=%(update_time)s' if alert.update_time else 'update_time=update_time',
                original_id=original_id
            )
            return self._updateone(update, vars(alert), returning=True)
        logger.error("Correlating alert '%s' without '%s' attribute", alert.id, ATTRIBUTE_ORIGINAL_ID)
        return alert  # should not happen

    def get_alert_history(self, alert, page=None, page_size=None):
        original_id = alert.attributes.get(ATTRIBUTE_ORIGINAL_ID) or alert.id
        select = """
            SELECT resource, environment, service, "group", tags, attributes, origin, customer, h.*
              FROM alerts, unnest(history[1:{limit}]) h
             WHERE alerts.id='{original_id}'
          ORDER BY update_time DESC
            """.format(
            original_id=original_id,
            limit=current_app.config['HISTORY_LIMIT']
        )
        return [
            Record(
                id=h.id,
                resource=h.resource,
                event=h.event,
                environment=h.environment,
                severity=h.severity,
                status=h.status,
                service=h.service,
                group=h.group,
                value=h.value,
                text=h.text,
                tags=h.tags,
                attributes=h.attributes,
                origin=h.origin,
                update_time=h.update_time,
                user=getattr(h, 'user', None),
                timeout=getattr(h, 'timeout', None),
                type=h.type,
                customer=h.customer
            ) for h in self._fetchall(select, vars(alert), limit=page_size, offset=(page - 1) * page_size)
        ]

    def get_severity(self, alert):
        original_id = alert.attributes.get(ATTRIBUTE_ORIGINAL_ID) or alert.id
        select = """
            SELECT severity FROM alerts
             WHERE alerts.id='{original_id}'
            """.format(original_id=original_id)
        return self._fetchone(select, vars(alert)).severity

    def get_status(self, alert):
        original_id = alert.attributes.get(ATTRIBUTE_ORIGINAL_ID) or alert.id
        select = """
            SELECT status FROM alerts
             WHERE alerts.id='{original_id}'
            """.format(original_id=original_id)
        return self._fetchone(select, vars(alert)).status

    def is_flapping(self, alert, window=1800, count=2):
        # TODO: How to manage this with deduplication?
        return super(Backend, self).is_flapping(alert, window, count)

    def update_attributes(self, id, old_attrs_ignored, new_attrs):  # noqa
        # old_attrs is ignored. Merge will be done directly by postgres to avoid concurrency problems.
        # Attribute is kept in function to ensure compatibility with backend class.
        # old_attrs.update(new_attrs)
        # attrs = {k: v for k, v in old_attrs.items() if v is not None}
        attrs = {k: v for k, v in new_attrs.items() if v is not None}
        update = """
            UPDATE alerts
            SET attributes=attributes || %(attrs)s
            WHERE id=%(id)s OR id LIKE %(like_id)s
            RETURNING attributes
        """
        return self._updateone(update, {'id': id, 'like_id': id + '%', 'attrs': attrs}, returning=True).attributes

    def get_expired(self, expired_threshold, info_threshold):
        # delete 'expired' alerts older than "expired_threshold" seconds
        # 'closed' alerta older than DELETE_CLOSED_AFTER config seconds
        # and 'informational' alerts older than "info_threshold" seconds

        closed_threshold = current_app.config.get('DELETE_CLOSED_AFTER', expired_threshold)
        if closed_threshold:
            delete = """
                DELETE FROM alerts
                 WHERE (status = 'closed'
                        AND last_receive_time < (NOW() at time zone 'utc' - INTERVAL '%(closed_threshold)s seconds'))
            """
            self._deleteall(delete, {'closed_threshold': closed_threshold})

        if expired_threshold:
            delete = """
                DELETE FROM alerts
                 WHERE (status = 'expired'
                        AND last_receive_time < (NOW() at time zone 'utc' - INTERVAL '%(expired_threshold)s seconds'))
            """
            self._deleteall(delete, {'expired_threshold': expired_threshold})

        if info_threshold:
            delete = """
                DELETE FROM alerts
                 WHERE (severity=%(inform_severity)s
                        AND last_receive_time < (NOW() at time zone 'utc' - INTERVAL '%(info_threshold)s seconds'))
            """
            self._deleteall(delete, {'inform_severity': alarm_model.DEFAULT_INFORM_SEVERITY,
                                     'info_threshold': info_threshold})

        # get list of alerts to be newly expired
        select = """
            SELECT *
              FROM alerts
             WHERE status NOT IN ('expired') AND COALESCE(timeout, {timeout})!=0
               AND (last_receive_time + INTERVAL '1 second' * timeout) < NOW() at time zone 'utc'
        """.format(timeout=current_app.config['ALERT_TIMEOUT'])

        return self._fetchall(select, {})

    # NEW methods

    def get_must_close_ids(self, limit=100):
        select = """
            SELECT id 
              FROM alerts
             WHERE status not in ('closed', 'expired')
               AND (attributes->>'autoCloseAt')::timestamptz < current_timestamp
        """
        return [x[0] for x in self._fetchall(select, {}, limit=limit)]

    def fetchall_no_limit(self, query, vars_):
        """
        Return all matching rows.
        """
        cursor = self.get_db().cursor()
        self._log(cursor, query, vars_)
        cursor.execute(query, vars_)
        return cursor.fetchall()
