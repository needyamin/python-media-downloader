#!/bin/bash
cd "$(dirname "$0")"

if [ ! -f "venv/bin/activate" ]; then
  echo "Run ./setup.sh first"
  exit 1
fi

source venv/bin/activate

if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

BIND=${BIND:-0.0.0.0}
PORT=${PORT:-8092}
exec gunicorn config.wsgi:application --bind "${BIND}:${PORT}" --workers 2 --timeout 300
