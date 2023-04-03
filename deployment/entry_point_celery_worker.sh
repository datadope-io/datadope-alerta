#!/bin/bash

celery -A "iometrics_alerta.plugins.bgtasks.celery" worker --loglevel=${CELERY_WORKER_LOGLEVEL} --concurrency=${CELERY_CONCURRENCY}
