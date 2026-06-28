#!/bin/bash
cd "$(dirname "$0")"

if [ ! -f "venv/bin/activate" ]; then
  echo "Run ./setup.sh first"
  exit 1
fi

source venv/bin/activate

if [ -f ".env" ]; then
  set -a
  source .env
  set +a
fi

PORT=${PORT:-80}
echo "Starting on http://0.0.0.0:$PORT"
exec gunicorn config.wsgi:application --bind "0.0.0.0:$PORT" --workers 2 --timeout 300
