#!/bin/bash
set -e

cd "$(dirname "$0")"
ROOT="$(pwd)"

echo "=== Media Downloader Setup ==="

# Python
if ! command -v python3 &>/dev/null; then
  echo "Error: python3 not found. Install Python 3.10+ first."
  exit 1
fi

# Venv (recreate if broken or uploaded from Windows)
if [ ! -f "venv/bin/activate" ]; then
  echo "[1/6] Creating virtual environment..."
  rm -rf venv
  python3 -m venv venv
else
  echo "[1/6] Virtual environment OK."
fi

source venv/bin/activate

echo "[2/6] Installing dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt
pip install -q -U yt-dlp

# Allow port 80 without root (optional)
if [ -f "venv/bin/gunicorn" ] && command -v setcap &>/dev/null; then
  setcap 'cap_net_bind_service=+ep' venv/bin/gunicorn 2>/dev/null || true
fi

# .env
if [ ! -f ".env" ]; then
  echo "[3/6] Creating .env ..."
  SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
  ADMIN=$(python3 -c "import secrets; print(secrets.token_urlsafe(12))")
  read -p "Domain (ALLOWED_HOSTS, e.g. example.com or *): " DOMAIN
  DOMAIN=${DOMAIN:-*}
  cat > .env <<EOF
SECRET_KEY=$SECRET
DEBUG=False
ALLOWED_HOSTS=$DOMAIN
ADMIN_CODE=$ADMIN
PORT=80
EOF
  echo "  Admin code saved in .env: $ADMIN"
else
  echo "[3/6] .env already exists — skipping."
fi

echo "[4/6] Creating folders..."
mkdir -p downloads staticfiles
chmod 755 downloads

echo "[5/6] Collecting static files..."
python manage.py collectstatic --noinput

echo "[6/6] Done."

# systemd (optional)
if [ "$1" = "--systemd" ] && command -v systemctl &>/dev/null; then
  SERVICE="/etc/systemd/system/downloader.service"
  echo "Installing systemd service..."
  sudo tee "$SERVICE" > /dev/null <<EOF
[Unit]
Description=Media Downloader
After=network.target

[Service]
User=${SUDO_USER:-$USER}
WorkingDirectory=$ROOT
EnvironmentFile=$ROOT/.env
ExecStart=$ROOT/venv/bin/gunicorn config.wsgi:application --bind 0.0.0.0:80 --workers 2 --timeout 300
Restart=always

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable downloader
  sudo systemctl restart downloader
  echo "Service running: sudo systemctl status downloader"
else
  echo ""
  echo "Start now:  ./start.sh"
  echo "Production:   ./setup.sh --systemd"
fi
