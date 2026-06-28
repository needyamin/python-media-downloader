#!/bin/bash
cd "$(dirname "$0")"
chmod +x setup.sh start.sh 2>/dev/null || true

echo "=== Health check ==="
echo -n "Gunicorn service: "
systemctl is-active downloader 2>/dev/null || echo "not installed"

echo -n "Port 8092: "
if curl -sf -o /dev/null -w "%{http_code}" -H "Host: download.needyamin.site" http://127.0.0.1:8092/ 2>/dev/null | grep -q 200; then
  echo "OK (200)"
else
  echo "FAIL — run: sudo ./setup.sh"
  curl -sI -H "Host: download.needyamin.site" http://127.0.0.1:8092/ | head -3
fi

echo -n "cloudflared: "
systemctl is-active cloudflared 2>/dev/null || pgrep -x cloudflared >/dev/null && echo "running" || echo "NOT RUNNING (502 if tunnel used)"

echo -n "Health API: "
curl -sf -H "Host: download.needyamin.site" http://127.0.0.1:8092/health/ 2>/dev/null || echo "FAIL"

echo -n "Deno: "
command -v deno >/dev/null && deno --version | head -1 || echo "MISSING — run sudo ./setup.sh"

echo -n "yt-dlp: "
source venv/bin/activate 2>/dev/null && yt-dlp --version || echo "unknown"

echo ""
echo "Tunnel must be: http://127.0.0.1:8092"
