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

echo ""
echo "Tunnel must be: http://127.0.0.1:8092"
echo "CloudPanel App Port: 8092"
