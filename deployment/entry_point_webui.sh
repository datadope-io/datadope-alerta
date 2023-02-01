#!/bin/bash

cd /app/dist
echo "{\"endpoint\": \"${ALERTA_SERVER_ENDPOINT}\"}" > config.json

python -m http.server "${ALERTA_WEBUI_PORT}"
