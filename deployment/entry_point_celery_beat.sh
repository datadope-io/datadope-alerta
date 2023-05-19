#!/bin/bash

celery -A "iometrics_alerta.bgtasks.celery" beat -s "${CELERY_BEAT_DATABASE}" --loglevel=${CELERY_BEAT_LOGLEVEL}