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

## Setup

```bash
pip install -r requirements.txt
python manage.py runserver
```

Open http://127.0.0.1:8000

**Admin:** http://127.0.0.1:8000/admin/ — default code in `config/settings.py` (`ADMIN_CODE`)

## Usage

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
