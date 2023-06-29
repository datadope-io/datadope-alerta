FROM python:3.10-slim AS builder

ARG TARGETPLATFORM
ARG VERSION
ENV VERSION=${VERSION:-2.1.0}

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=.

# Install dependencies
RUN apt-get -y update \
    && apt-get -y install build-essential git libpq-dev libsasl2-dev python-dev libldap2-dev libssl-dev

# Install pipenv
RUN pip install --upgrade pip \
    && pip install pipenv

WORKDIR /app

# Install python dependencies
COPY deployment/Pipfile /app/
RUN pipenv lock \
    && pipenv install --system

# Create packages for datadope-alerta
COPY VERSION LICENSE README.md setup.py MANIFEST.in /app/
COPY datadope_alerta /app/datadope_alerta

RUN python -m setup bdist_wheel

# Install datadope-alerta
WORKDIR /
RUN pip install /app/dist/datadope_alerta-${VERSION}-py3-none-any.whl

# Cleaning
RUN apt-get -y purge --auto-remove build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

FROM python:3.10-slim

ARG TARGETPLATFORM

LABEL io.datadope.name = "datadope-alerta" \
      io.datadope.vendor = "DataDope" \
      io.datadope.url = "https://www.datadope.io"

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=.

# VARIABLES DE ENTORNO CON VALORES POR DEFECTO QUE PUEDEN CAMBIARSE AL EJECUTAR EL DOCKER
ENV ALERTA_SVR_CONF_FILE=/etc/datadope-alerta/alertad.conf \
    CELERY_WORKER_LOGLEVEL=info \
    CELERY_BEAT_LOGLEVEL=info \
    CELERY_BEAT_DATABASE=/var/tmp/celerybeat-schedule \
    CELERY_FLOWER_PORT=5555 \
    AUTO_CLOSE_TASK_INTERVAL=60.0 \
    CELERY_CONCURRENCY=10

COPY --from=builder /usr/local/lib/python3.10/site-packages/ /usr/local/lib/python3.10/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/
COPY --from=builder /usr/lib/ /usr/lib/
COPY config_example/* /etc/datadope-alerta/

RUN groupadd alerta && useradd --create-home --home-dir /home/alerta -u 1000 -g alerta alerta
WORKDIR /home/alerta

COPY deployment/entry_point_celery* /usr/local/bin/
USER alerta
CMD entry_point_celery_worker.sh
# CMD ./entry_point_celery_beat.sh
# CMD ./entry_point_celery_flower.sh
