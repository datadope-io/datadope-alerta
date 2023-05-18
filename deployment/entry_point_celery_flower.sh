#!/bin/bash

celery -A "iometrics_alerta.bgtasks.celery" flower --port="${CELERY_FLOWER_PORT}"
