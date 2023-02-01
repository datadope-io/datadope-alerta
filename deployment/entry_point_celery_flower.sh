#!/bin/bash

celery -A "iometrics_alerta.plugins.bgtasks.celery" flower --port="${CELERY_FLOWER_PORT}"
