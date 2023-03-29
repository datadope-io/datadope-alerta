FROM python:3.10-slim

ARG TARGETPLATFORM

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=. \
    ALERTA_WEBUI_PORT=8000 \
    ALERTA_SERVER_ENDPOINT=http://localhost:8001

WORKDIR /app

ADD  https://github.com/datadope-io/alerta-webui/releases/latest/download/alerta-webui.tar.gz .
RUN tar -xzvf alerta-webui.tar.gz \
    && rm alerta-webui.tar.gz

WORKDIR /app/dist
COPY deployment/logos /app/dist/logos
COPY deployment/entry_point_webui.sh /usr/local/bin

RUN useradd -ms /bin/bash -u 1000 webui && \
    chown -R webui:0 /app
USER webui

CMD entry_point_webui.sh
