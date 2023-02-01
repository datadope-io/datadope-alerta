#!/bin/bash
set -e

ADMIN_USER=${ADMIN_USERS%%,*}
ADMIN_PASSWORD=${ADMIN_PASSWORD:-alerta}
MAXAGE=${ADMIN_KEY_MAXAGE:-315360000}  # default=10 years

# env | sort

sleep 5

# Init admin users and API keys
if [ -n "${ADMIN_USERS}" ]; then
  echo "# Create admin users."
  alertad user --all --password "${ADMIN_PASSWORD}" || true
  echo "# Create admin API keys."
  alertad key --all > /dev/null

  # Create user-defined API key, if required
  if [ -n "${API_KEY}" ]; then
    echo "# Create user-defined admin API key."
    alertad key --username "${ADMIN_USER}" --key "${API_KEY}" --duration "${MAXAGE}" > /dev/null
  fi
fi

gunicorn --preload -w "${GUNICORN_WORKERS}" -b "${GUNICORN_BIND}" --timeout "${GUNICORN_TIMEOUT}" wsgi:app
