import shutil
import threading
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from django.conf import settings

from .tasks import schedule_delete, update_job

STREAM_HINTS = ('.m3u8', '.mpd', '/hls/', 'playlist', 'manifest', '.m3u8?')
DIRECT_EXT = ('.mp4', '.webm', '.mkv', '.ts', '.mp3', '.m4a', '.aac', '.flv')

PP_LABELS = {
    'FFmpegExtractAudio': 'Converting to MP3',
    'FFmpegMerger': 'Merging video + audio',
    'FFmpegVideoConvertor': 'Converting video',
    'FFmpegMetadata': 'Adding metadata',
}


def get_ffmpeg_path() -> str | None:
    path = shutil.which('ffmpeg')
    if path:
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def ffmpeg_available() -> bool:
    return get_ffmpeg_path() is not None


def is_stream_url(url: str) -> bool:
    u = url.lower()
    if any(h in u for h in STREAM_HINTS):
        return True
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in DIRECT_EXT)


UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'


def _friendly_error(exc: Exception) -> str:
    msg = str(exc)
    low = msg.lower()
    if 'login required' in low or 'empty media' in low or 'not available' in low or 'instagram' in low:
        return 'This link is blocked by the site (Instagram often needs login). Try YouTube or a direct .mp4 link.'
    if 'rate-limit' in low:
        return 'Too many requests. Wait a few minutes and try again.'
    return msg[:600]


def _ydl_extract(opts: dict, url: str, download: bool = False):
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=download)


def _site_opts(url: str) -> dict:
    u = url.lower()
    headers = {'User-Agent': UA}
    if 'instagram.com' in u:
        headers['Referer'] = 'https://www.instagram.com/'
    elif 'tiktok.com' in u:
        headers['Referer'] = 'https://www.tiktok.com/'
    return {'http_headers': headers}


def _base_opts(url: str = '') -> dict:
    opts = {
        'quiet': True,
        'no_warnings': True,
        'restrictfilenames': False,
        'windowsfilenames': True,
        'retries': 5,
        'fragment_retries': 5,
        'socket_timeout': 30,
        **_site_opts(url),
    }
    if ffmpeg_available():
        opts['ffmpeg_location'] = get_ffmpeg_path()
    return opts


def _fmt_speed(bps) -> str:
    if not bps:
        return ''
    if bps > 1_000_000:
        return f'{bps / 1_000_000:.1f} MB/s'
    return f'{bps / 1_000:.0f} KB/s'


def _fmt_eta(sec) -> str:
    if not sec:
        return ''
    sec = int(sec)
    return f'{sec // 60}:{sec % 60:02d}'


def _sort_formats(formats: list) -> list:
    videos = [f for f in formats if f['kind'] == 'video']
    audios = [f for f in formats if f['kind'] == 'audio']
    videos.sort(key=lambda x: (x['height'], x['ext'] in ('mp4', 'm4v')), reverse=True)
    audios.sort(key=lambda x: x['abr'], reverse=True)
    for v in videos:
        v['label'] = f"{v['height']}p MP4" if v['height'] else 'MP4 (best)'
    for a in audios:
        a['label'] = f"MP3 {int(a['abr'])}kbps" if a['abr'] else 'MP3 (best)'
    return videos[:15] + audios[:15]


def get_media_info(url: str) -> dict:
    opts = {**_base_opts(url), 'extract_flat': False}
    info = _ydl_extract(opts, url, download=False)

    formats = []
    seen = set()
    for f in info.get('formats') or []:
        ext = f.get('ext', '')
        height = f.get('height')
        vcodec = f.get('vcodec', 'none')
        acodec = f.get('acodec', 'none')
        if vcodec != 'none' and acodec != 'none':
            kind = 'video'
        elif vcodec != 'none':
            kind = 'video'
        elif acodec != 'none':
            kind = 'audio'
        else:
            continue
        key = (kind, height, f.get('abr'), ext)
        if key in seen:
            continue
        seen.add(key)
        formats.append({
            'format_id': str(f['format_id']),
            'kind': kind,
            'height': height or 0,
            'abr': f.get('abr') or 0,
            'ext': ext,
            'label': '',
        })

    formats = _sort_formats(formats)

    is_live = bool(info.get('is_live'))
    is_stream = is_stream_url(url) or info.get('protocol') in ('m3u8', 'm3u8_native', 'http_dash_segments')

    return {
        'title': info.get('title', 'Stream' if is_stream else 'Unknown'),
        'thumbnail': info.get('thumbnail'),
        'duration': info.get('duration'),
        'formats': formats,
        'is_live': is_live,
        'is_stream': is_stream,
        'ffmpeg': ffmpeg_available(),
        'note': _info_note(is_live, is_stream, ffmpeg_available()),
    }


def _info_note(is_live, is_stream, has_ffmpeg) -> str:
    parts = []
    if is_live:
        parts.append('Live stream — records until stream ends')
    elif is_stream:
        parts.append('Stream URL (HLS/DASH/direct) supported')
    if not has_ffmpeg:
        parts.append('FFmpeg not found — install for merge/MP3 convert')
    parts.append('Files auto-delete from server after 10 minutes')
    return ' · '.join(parts)


def _build_opts(url, format_choice, live_from_start, job_id):
    settings.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    out = str(settings.DOWNLOAD_DIR / '%(title)s.%(ext)s')
    has_ffmpeg = ffmpeg_available()

    post = []
    mp3_out = False

    if format_choice == 'audio':
        fmt = 'bestaudio/best'
        if has_ffmpeg:
            post = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}]
            mp3_out = True
        else:
            fmt = 'bestaudio[ext=m4a]/bestaudio/best'
    elif format_choice == 'video':
        if has_ffmpeg:
            fmt = 'bestvideo[ext=mp4]+bestaudio/bestvideo+bestaudio/best'
        else:
            fmt = 'best[ext=mp4]/best'
    elif '+' in format_choice:
        fmt = format_choice
    elif format_choice.isdigit():
        fmt = format_choice
        if has_ffmpeg:
            post = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}]
            mp3_out = True
    else:
        fmt = 'best[ext=mp4]/best'

    def progress_hook(d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            done = d.get('downloaded_bytes', 0)
            pct = round(done / total * 100, 1) if total else 0
            msg = 'Recording live stream...' if live_from_start or not total else 'Downloading...'
            if not total and done:
                msg = f'Downloading... {done // 1_000_000} MB'
            update_job(job_id,
                status='running', phase='downloading', percent=pct,
                speed=_fmt_speed(d.get('speed')),
                eta=_fmt_eta(d.get('eta')),
                message=msg,
            )
        elif d['status'] == 'finished':
            update_job(job_id, phase='processing', percent=95,
                       message='Download finished, processing...')

    def postprocessor_hook(d):
        pp = d.get('postprocessor', '')
        label = next((v for k, v in PP_LABELS.items() if k in pp), 'Processing')
        if d['status'] == 'started':
            update_job(job_id, phase='converting', percent=96, message=f'{label}...')
        elif d['status'] == 'processing':
            update_job(job_id, phase='converting', percent=98, message=f'{label}...')

    opts = {
        **_base_opts(url),
        'format': fmt,
        'outtmpl': out,
        'merge_output_format': 'mp4',
        'postprocessors': post,
        'hls_use_mpegts': True,
        'live_from_start': live_from_start,
        'concurrent_fragment_downloads': 4,
        'progress_hooks': [progress_hook],
        'postprocessor_hooks': [postprocessor_hook],
    }
    if not has_ffmpeg:
        opts.pop('merge_output_format', None)
    return opts, has_ffmpeg, format_choice, mp3_out


def run_download_job(job_id: str, url: str, format_choice: str, live_from_start: bool = False):
    try:
        update_job(job_id, status='running', phase='starting', message='Fetching media info...')
        opts, has_ffmpeg, fmt, mp3_out = _build_opts(url, format_choice, live_from_start, job_id)

        info = _ydl_extract(opts, url, download=True)
        with yt_dlp.YoutubeDL(opts) as ydl:
            path = Path(ydl.prepare_filename(info))
            if mp3_out:
                path = path.with_suffix('.mp3')
            elif has_ffmpeg and (fmt == 'video' or '+' in str(fmt)):
                path = path.with_suffix('.mp4')
            if not path.exists():
                matches = list(settings.DOWNLOAD_DIR.glob(f"{path.stem}*"))
                if matches:
                    path = max(matches, key=lambda p: p.stat().st_mtime)

        delete_at = schedule_delete(path)
        update_job(job_id,
            status='done', phase='done', percent=100,
            message='Ready! Download to your device below.',
            filename=path.name,
            filepath=str(path),
            url=f'/file/{job_id}/',
            delete_at=delete_at,
        )
    except Exception as e:
        err = _friendly_error(e)
        update_job(job_id, status='error', phase='error', message=err, error=err)


def start_download_job(url: str, format_choice: str, live_from_start: bool = False) -> str:
    from .tasks import create_job
    job_id = create_job()
    threading.Thread(
        target=run_download_job,
        args=(job_id, url, format_choice, live_from_start),
        daemon=True,
    ).start()
    return job_id
