#!/bin/bash

celery -A "datadope_alerta.bgtasks.celery" flower --port="${CELERY_FLOWER_PORT}"
