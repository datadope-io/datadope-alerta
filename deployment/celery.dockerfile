FROM python:3.10-slim AS builder

ARG TARGETPLATFORM
ARG VERSION
ENV VERSION=${VERSION:-0.2.0}

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=.

# Install dependencies
RUN apt-get -y update \
    && apt-get -y install build-essential git libpq-dev

# Install pipenv
RUN pip install --upgrade pip \
    && pip install pipenv

WORKDIR /app

# Install python dependencies
COPY deployment/Pipfile /app/
RUN pipenv lock \
    && pipenv install --system

# Create packages for iometrics-alerta
COPY VERSION LICENSE README.md setup*.py /app/
COPY iometrics_alerta /app/iometrics_alerta

RUN python -m setup_routing bdist_wheel \
    && python -m setup bdist_wheel

# Install iometrics-alerta
WORKDIR /
RUN pip install /app/dist/alerta_routing-${VERSION}-py3-none-any.whl \
    && pip install /app/dist/iometrics_alerta-${VERSION}-py3-none-any.whl

# Cleaning
RUN apt-get -y purge --auto-remove build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

FROM python:3.10-slim

ARG TARGETPLATFORM

LABEL io.datadope.name = "iometrics-alerta" \
      io.datadope.vendor = "DataDope" \
      io.datadope.url = "https://www.datadope.io"

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=.

# VARIABLES DE ENTORNO CON VALORES POR DEFECTO QUE PUEDEN CAMBIARSE AL EJECUTAR EL DOCKER
ENV ALERTA_SVR_CONF_FILE=/etc/iometrics-alerta/alertad.conf \
    CELERY_WORKER_LOGLEVEL=info \
    CELERY_BEAT_LOGLEVEL=info \
    CELERY_BEAT_DATABASE=/var/tmp/celerybeat-schedule \
    CELERY_FLOWER_PORT=5555 \
    AUTO_CLOSE_TASK_INTERVAL=60.0

COPY --from=builder /usr/local/lib/python3.10/site-packages/ /usr/local/lib/python3.10/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/
COPY --from=builder /usr/lib/ /usr/lib/
COPY config_example/* /etc/iometrics-alerta/

RUN groupadd user && useradd --create-home --home-dir /home/user -g user user
WORKDIR /home/user

COPY deployment/entry_point_celery* /usr/local/bin/
USER user
CMD entry_point_celery_worker.sh
# CMD ./entry_point_celery_beat.sh
# CMD ./entry_point_celery_flower.sh
