#!/bin/bash
cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
  echo "Run ./setup.sh first"
  exit 1
fi

source venv/bin/activate

if [ -f ".env" ]; then
  set -a
  source .env
  set +a
fi

echo "Starting on http://0.0.0.0:8000"
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 300
