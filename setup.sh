#!/bin/bash
set -e

cd "$(dirname "$0")"
ROOT="$(cd "$(dirname "$0")" && pwd)"
chmod +x setup.sh start.sh 2>/dev/null || true

DOMAIN="${DOMAIN:-download.needyamin.site}"
PORT="${PORT:-8092}"
BIND="${BIND:-0.0.0.0}"

echo "=== Media Downloader Setup ==="
echo "Domain: $DOMAIN | Port: $BIND:$PORT (Cloudflare tunnel)"

if ! command -v python3 &>/dev/null; then
  echo "Error: python3 not found."
  exit 1
fi

if [ ! -f "venv/bin/activate" ]; then
  echo "[1/7] Creating virtual environment..."
  rm -rf venv
  python3 -m venv venv
else
  echo "[1/7] Virtual environment OK."
fi

source venv/bin/activate

echo "[2/7] Installing dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt
pip install -q -U yt-dlp

echo "[2b/7] yt-dlp version: $(yt-dlp --version 2>/dev/null || echo unknown)"

echo "[2c/7] Installing Deno (required for YouTube & many sites)..."
if ! command -v deno &>/dev/null; then
  curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh 2>/dev/null \
    || curl -fsSL https://deno.land/install.sh | sh
  export PATH="/usr/local/bin:$HOME/.deno/bin:$PATH"
  ln -sf "$HOME/.deno/bin/deno" /usr/local/bin/deno 2>/dev/null || true
fi
echo "  deno: $(deno --version 2>/dev/null | head -1 || echo 'not found — install manually')"

set_env() {
  local key="$1" val="$2"
  if [ -f .env ] && grep -q "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=${val}|" .env
  else
    echo "${key}=${val}" >> .env
  fi
}

echo "[3/7] Configuring .env ..."
if [ ! -f ".env" ]; then
  SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
  ADMIN=$(python3 -c "import secrets; print(secrets.token_urlsafe(12))")
  cat > .env <<EOF
SECRET_KEY=$SECRET
DEBUG=False
ALLOWED_HOSTS=$DOMAIN,127.0.0.1,localhost
CSRF_TRUSTED_ORIGINS=https://$DOMAIN
ADMIN_CODE=$ADMIN
PORT=$PORT
BIND=$BIND
EOF
  echo "  Admin code: $ADMIN"
else
  set_env ALLOWED_HOSTS "$DOMAIN,127.0.0.1,localhost"
  set_env CSRF_TRUSTED_ORIGINS "https://$DOMAIN"
  set_env PORT "$PORT"
  set_env BIND "$BIND"
  grep -q '^SECRET_KEY=' .env || set_env SECRET_KEY "$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")"
fi

echo "[4/7] Creating folders..."
mkdir -p downloads staticfiles
chmod 755 downloads

echo "[5/7] Collecting static files..."
python manage.py collectstatic --noinput

install_systemd() {
  if [ "$(id -u)" = "0" ]; then
    SVC_USER="root"
    SVC_GROUP="root"
  else
    SVC_USER=$(stat -c '%U' "$ROOT")
    SVC_GROUP=$(stat -c '%G' "$ROOT")
  fi

  DENO_PATH="/usr/local/bin"
  [ -x "$HOME/.deno/bin/deno" ] && DENO_PATH="$HOME/.deno/bin:/usr/local/bin"

  echo "[6/7] Installing systemd service (auto-start on boot)..."
  tee /etc/systemd/system/downloader.service > /dev/null <<EOF
[Unit]
Description=Media Downloader ($DOMAIN)
After=network.target cloudflared.service

[Service]
Type=simple
User=$SVC_USER
Group=$SVC_GROUP
WorkingDirectory=$ROOT
EnvironmentFile=-$ROOT/.env
Environment=PATH=$DENO_PATH:/usr/bin:/bin
ExecStart=/bin/bash $ROOT/start.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl reset-failed downloader 2>/dev/null || true
  systemctl enable downloader
  systemctl restart downloader
  sleep 2
  systemctl status downloader --no-pager || true
  echo ""
  echo "Live: https://$DOMAIN"
  echo "Tunnel target: http://$BIND:$PORT"
}

if command -v systemctl &>/dev/null && [ "$(id -u)" = "0" ]; then
  install_systemd
else
  echo "[6/7] Skipping systemd — run: sudo ./setup.sh"
fi

echo "[7/7] Done."
if [ "$(id -u)" != "0" ]; then
  echo "Manual start: ./start.sh"
  echo "Auto-start:   sudo ./setup.sh"
fi
