#!/bin/bash

celery -A "datadope_alerta.bgtasks.celery" beat -s "${CELERY_BEAT_DATABASE}" --loglevel=${CELERY_BEAT_LOGLEVEL}