# Media Downloader

> **Educational project only.** For learning Python, Django, and media handling — not for piracy or copyright infringement.

Lightweight Django app to download video/audio from many sites via [yt-dlp](https://github.com/yt-dlp/yt-dlp).

## Disclaimer

**Read this before using the project.**

- This software is shared **for education and research** (e.g. learning Django, APIs, FFmpeg, streaming formats).
- **The authors and contributors are not responsible** for how you use it, or for any copyright violations, DMCA claims, terms-of-service breaches, or other legal issues.
- **You are solely responsible** for complying with copyright law, platform rules, and laws in your country.
- **Do not download** videos, music, or other media unless you own the rights, have **explicit permission**, or the content is **legally free to use** (e.g. public domain, Creative Commons where allowed).
- Do not use this tool to bypass paywalls, DRM, or protections on protected content.
- Do not redistribute downloaded copyrighted material.

If you do not agree, **do not use this software**.

## License

This project is licensed under the [MIT License](LICENSE), with the educational-use notice included in that file.

## Requirements

- Python 3.10+
- FFmpeg — auto-included via `imageio-ffmpeg` (or use system FFmpeg)

## Setup (local)

```bash
pip install -r requirements.txt
python manage.py runserver
```

## Setup (live server — CloudPanel + Cloudflare)

Cloudflare tunnel → `http://localhost:8092` → this app.

```bash
chmod +x setup.sh start.sh
sudo ./setup.sh
```

Defaults:
- Domain: `download.needyamin.site`
- Port: `8092` on `127.0.0.1`
- Auto-start on boot (systemd when run as root)

Cloudflare tunnel config:
```yaml
ingress:
  - hostname: download.needyamin.site
    service: http://localhost:8092
```

**CloudPanel:** Sites → download.needyamin.site → **Python Settings** → **App Port** = `8092` → Save.

Verify:
```bash
curl http://127.0.0.1:8092
systemctl status downloader
```

## Setup (local)

1. Paste a URL
2. Click **Get Info**
3. Download video (MP4) or audio (MP3)

Files save to `downloads/` and auto-delete from the server after 10 minutes.

## Configuration

| Setting | Location | Default |
|---------|----------|---------|
| Admin code | `ADMIN_CODE` env or `settings.py` | `admin1234` |
| File retention | `FILE_RETENTION_SECONDS` | `600` (10 min) |
| Secret key | `SECRET_KEY` env | change in production |

## Why some links fail

Sites like Instagram, Netflix, or private posts **block automated downloads on purpose**:

- **Copyright** — they control who can save media
- **Login walls** — video URL is hidden until you sign in
- **Anti-bot** — servers detect tools (not a real browser) and refuse
- **Rate limits** — too many requests from one IP

This is enforced **on their server**, not in this app. No downloader can guarantee every site.

**What usually works:** YouTube, TikTok public posts, direct `.mp4` / `.m3u8` links, open streams.

**If a link fails:** try a **public** URL, a **direct file link**, or `pip install -U yt-dlp`.

## Third-party tools

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — media extraction (subject to its own license)
- [FFmpeg](https://ffmpeg.org/) — media processing
- [Django](https://www.djangoproject.com/)

Use of those tools may be subject to additional terms and laws.

## Deploy on live server (VPS / Linux)

Quick: upload code → `chmod +x setup.sh start.sh` → `./setup.sh` → `./start.sh`

Manual steps below if you prefer.

```bash
cd /var/www/downloader-python
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -U yt-dlp
```

### 3. Environment variables

```bash
export SECRET_KEY="your-long-random-secret-key"
export DEBUG="False"
export ALLOWED_HOSTS="yourdomain.com,www.yourdomain.com"
export ADMIN_CODE="your-strong-admin-code"
```

Or create a `.env` file and load it in your service (do not commit `.env`).

### 4. Collect static files

```bash
python manage.py collectstatic --noinput
mkdir -p downloads
chmod 755 downloads
```

### 5. Test run

```bash
gunicorn config.wsgi:application --bind 127.0.0.1:8000
```

Open `http://SERVER_IP:8000` (if firewall allows). Stop with Ctrl+C.

### 6. Run forever with systemd

Create `/etc/systemd/system/downloader.service`:

```ini
[Unit]
Description=Media Downloader
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/downloader-python
Environment="SECRET_KEY=your-secret"
Environment="DEBUG=False"
Environment="ALLOWED_HOSTS=yourdomain.com"
Environment="ADMIN_CODE=your-admin-code"
ExecStart=/var/www/downloader-python/venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 2 --timeout 300
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable downloader
sudo systemctl start downloader
sudo systemctl status downloader
```

### 7. Nginx reverse proxy (recommended)

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 300s;
        client_max_body_size 50M;
    }
}
```

Enable SSL with Certbot: `sudo certbot --nginx -d yourdomain.com`

### 8. Shared hosting (cPanel)

Many shared hosts **cannot** run this (no long-running Python, no yt-dlp/ffmpeg). You need a **VPS** or cloud server (DigitalOcean, Hetzner, AWS EC2, etc.).

### Checklist

| Item | Notes |
|------|-------|
| `DEBUG=False` | Required on live |
| `ALLOWED_HOSTS` | Your domain name |
| `SECRET_KEY` | Random string |
| `ADMIN_CODE` | Change from default |
| `downloads/` | Writable folder |
| Port 8000 or Nginx | Public access |
| `pip install -U yt-dlp` | Keep updated on server |
