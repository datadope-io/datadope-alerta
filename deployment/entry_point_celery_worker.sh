#!/bin/bash

celery -A "datadope_alerta.bgtasks.celery" worker --loglevel=${CELERY_WORKER_LOGLEVEL} --concurrency=${CELERY_CONCURRENCY}
