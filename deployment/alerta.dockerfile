FROM python:3.10-slim AS builder

ARG TARGETPLATFORM
ARG VERSION
ENV VERSION=${VERSION:-2.0.0}

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

# Default values for env vars.
ENV ALERTA_SVR_CONF_FILE=/etc/datadope-alerta/alertad.conf \
    GUNICORN_BIND=0.0.0.0:8000 \
    GUNICORN_WORKERS=8 \
    GUNICORN_TIMEOUT=600 \
    CELERY_WORKER_LOGLEVEL=info \
    CELERY_BEAT_LOGLEVEL=info \
    CELERY_BEAT_DATABASE=/var/tmp/celerybeat-schedule \
    AUTO_CLOSE_TASK_INTERVAL=60.0

# Env vars that should be provided when running docker:
# SECRET_KEY
# ADMIN_USERS
# ADMIN_PASSWORD
# API_KEY

COPY --from=builder /usr/local/lib/python3.10/site-packages/ /usr/local/lib/python3.10/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/
COPY --from=builder /usr/lib/ /usr/lib/
COPY config_example/* /etc/datadope-alerta/

WORKDIR /app
COPY deployment/iom_wsgi.py /app/
COPY deployment/entry_point_alerta.sh /usr/local/bin/

RUN useradd -ms /bin/bash -u 1000 alerta && \
    chown -R alerta:0 /app
USER alerta

# EXPOSE 8000
CMD entry_point_alerta.sh
