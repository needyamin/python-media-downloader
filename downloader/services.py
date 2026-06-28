import json
import logging
import re
import shutil
import threading
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from django.conf import settings

from .tasks import schedule_delete, update_job

logger = logging.getLogger(__name__)

STREAM_HINTS = ('.m3u8', '.mpd', '/hls/', 'manifest.m3u8', '/master.m3u8')
DIRECT_EXT = ('.mp4', '.webm', '.mkv', '.ts', '.mp3', '.m4a', '.aac', '.flv')

PP_LABELS = {
    'FFmpegExtractAudio': 'Converting to MP3',
    'FFmpegMerger': 'Merging video + audio',
    'FFmpegVideoConvertor': 'Converting video',
    'FFmpegMetadata': 'Adding metadata',
}

UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
)

REFERRERS = {
    'youtube.com': 'https://www.youtube.com/',
    'youtu.be': 'https://www.youtube.com/',
    'instagram.com': 'https://www.instagram.com/',
    'tiktok.com': 'https://www.tiktok.com/',
    'facebook.com': 'https://www.facebook.com/',
    'fb.watch': 'https://www.facebook.com/',
    'twitter.com': 'https://twitter.com/',
    'x.com': 'https://x.com/',
    'reddit.com': 'https://www.reddit.com/',
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


def _referer(url: str) -> str:
    u = url.lower()
    for key, ref in REFERRERS.items():
        if key in u:
            return ref
    return urlparse(url).scheme + '://' + urlparse(url).netloc + '/'


def _extractor_args(url: str) -> dict:
    u = url.lower()
    args = {}
    if 'youtube.com' in u or 'youtu.be' in u:
        args['youtube'] = {'player_client': ['android', 'web', 'ios']}
    if 'tiktok.com' in u:
        args['tiktok'] = {'api_hostname': 'api.tiktokv.com'}
    return args


def _deno_available() -> bool:
    return shutil.which('deno') is not None


def _base_opts(url: str = '') -> dict:
    opts = {
        'quiet': True,
        'no_warnings': True,
        'restrictfilenames': False,
        'windowsfilenames': True,
        'retries': 10,
        'fragment_retries': 10,
        'socket_timeout': 60,
        'geo_bypass': True,
        'nocheckcertificate': True,
        'http_headers': {
            'User-Agent': UA,
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': _referer(url) if url else 'https://www.google.com/',
        },
    }
    ext = _extractor_args(url)
    if ext:
        opts['extractor_args'] = ext
    if _deno_available():
        opts['js_runtimes'] = {'deno': {}}
    if ffmpeg_available():
        opts['ffmpeg_location'] = get_ffmpeg_path()
    return opts


def _friendly_error(exc: Exception) -> str:
    msg = str(exc).strip()
    low = msg.lower()
    if 'sign in' in low or 'login' in low or 'empty media' in low:
        return 'Site blocked this link (login required). Try a public URL or direct .mp4 link.'
    if 'rate' in low and 'limit' in low:
        return 'Rate limited. Wait a few minutes and try again.'
    if 'deno' in low or 'node' in low or 'javascript' in low:
        return 'Server needs Deno for downloads. Run: sudo ./setup.sh'
    if 'unable to extract' in low or 'unsupported url' in low:
        return 'Could not read this URL. Check the link or try a direct video file URL.'
    return msg[:500] if msg else 'Download failed. Try another link.'


def _ydl_extract(opts: dict, url: str, download: bool = False):
    attempts = [opts]
    u = url.lower()
    if 'youtube.com' in u or 'youtu.be' in u:
        fb = {**opts, 'extractor_args': {'youtube': {'player_client': ['android']}}}
        attempts.append(fb)

    last_err = None
    for o in attempts:
        try:
            with yt_dlp.YoutubeDL(o) as ydl:
                return ydl.extract_info(url, download=download)
        except Exception as e:
            last_err = e
            logger.warning('yt-dlp failed: %s', e)
    raise last_err


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


def _is_playlist(info: dict) -> bool:
    if info.get('_type') == 'playlist':
        return True
    entries = info.get('entries')
    return bool(entries and len(entries) > 1)


def _playlist_count(info: dict) -> int:
    n = info.get('playlist_count')
    if n:
        return int(n)
    entries = info.get('entries') or []
    return len([e for e in entries if e])


def _first_entry_url(info: dict) -> str | None:
    for e in info.get('entries') or []:
        if not e:
            continue
        return e.get('url') or e.get('webpage_url') or (
            f'https://www.youtube.com/watch?v={e["id"]}' if e.get('id') else None
        )
    return None


def _formats_from_info(info: dict) -> list:
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
    return _sort_formats(formats)


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
    url = url.strip()
    if not url:
        raise ValueError('URL required')
    opts = {**_base_opts(url), 'extract_flat': 'in_playlist', 'skip_download': True}
    info = _ydl_extract(opts, url, download=False)

    is_playlist = _is_playlist(info)
    entry_count = _playlist_count(info) if is_playlist else 0

    if is_playlist:
        sample_url = _first_entry_url(info)
        if sample_url:
            sample_opts = {**_base_opts(sample_url), 'skip_download': True, 'noplaylist': True}
            try:
                sample = _ydl_extract(sample_opts, sample_url, download=False)
                formats = _formats_from_info(sample)
            except Exception:
                formats = [{'format_id': 'best', 'kind': 'video', 'height': 0, 'abr': 0, 'ext': 'mp4', 'label': 'Best available'}]
        else:
            formats = [{'format_id': 'best', 'kind': 'video', 'height': 0, 'abr': 0, 'ext': 'mp4', 'label': 'Best available'}]
        title = info.get('title') or 'Playlist'
        thumb = info.get('thumbnail') or (info.get('entries') or [{}])[0].get('thumbnail')
        note = f'Playlist · {entry_count} videos · downloads as ZIP · Files auto-delete after 10 minutes'
        return {
            'title': title,
            'thumbnail': thumb,
            'duration': None,
            'formats': formats,
            'is_live': False,
            'is_stream': False,
            'is_playlist': True,
            'entry_count': entry_count,
            'ffmpeg': ffmpeg_available(),
            'note': note,
        }

    formats = _formats_from_info(info)
    if not formats:
        formats = [{'format_id': 'best', 'kind': 'video', 'height': 0, 'abr': 0, 'ext': 'mp4', 'label': 'Best available'}]
    is_live = bool(info.get('is_live'))
    is_stream = is_stream_url(url) or info.get('protocol') in ('m3u8', 'm3u8_native', 'http_dash_segments')

    return {
        'title': info.get('title', 'Stream' if is_stream else 'Unknown'),
        'thumbnail': info.get('thumbnail'),
        'duration': info.get('duration'),
        'formats': formats,
        'is_live': is_live,
        'is_stream': is_stream,
        'is_playlist': False,
        'entry_count': 0,
        'ffmpeg': ffmpeg_available(),
        'note': _info_note(is_live, is_stream, ffmpeg_available()),
    }


def _info_note(is_live, is_stream, has_ffmpeg) -> str:
    parts = []
    if is_live:
        parts.append('Live stream — records until stream ends')
    elif is_stream:
        parts.append('Stream URL supported')
    if not has_ffmpeg:
        parts.append('FFmpeg missing — run setup.sh')
    parts.append('Files auto-delete after 10 minutes')
    return ' · '.join(parts)


def _build_opts(url, format_choice, live_from_start, job_id, is_playlist=False):
    settings.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    if is_playlist:
        job_dir = settings.DOWNLOAD_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        out = str(job_dir / '%(playlist_index)02d - %(title)s.%(ext)s')
    else:
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
            idict = d.get('info_dict') or {}
            idx, ptotal = idict.get('playlist_index'), idict.get('playlist_count')
            if idx and ptotal:
                msg = f'Downloading video {idx}/{ptotal}...'
            elif live_from_start or not total:
                msg = 'Recording live stream...' if live_from_start else 'Downloading...'
            else:
                msg = 'Downloading...'
            if not total and done:
                msg = f'{msg} {done // 1_000_000} MB'
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
        'ignoreerrors': is_playlist,
    }
    if not has_ffmpeg:
        opts.pop('merge_output_format', None)
    return opts, has_ffmpeg, format_choice, mp3_out, is_playlist


def _zip_folder(folder: Path, zip_path: Path):
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(folder.iterdir()):
            if f.is_file():
                zf.write(f, f.name)


def run_download_job(job_id: str, url: str, format_choice: str, live_from_start: bool = False):
    try:
        update_job(job_id, status='running', phase='starting', message='Fetching media info...')
        flat_opts = {**_base_opts(url), 'extract_flat': 'in_playlist', 'skip_download': True}
        meta = _ydl_extract(flat_opts, url, download=False)
        is_playlist = _is_playlist(meta)

        opts, has_ffmpeg, fmt, mp3_out, is_playlist = _build_opts(
            url, format_choice, live_from_start, job_id, is_playlist
        )

        info = _ydl_extract(opts, url, download=True)

        if is_playlist:
            job_dir = settings.DOWNLOAD_DIR / job_id
            files = [f for f in job_dir.iterdir() if f.is_file()]
            if not files:
                raise ValueError('Playlist download failed — no files saved')
            zip_path = settings.DOWNLOAD_DIR / f'{job_id}.zip'
            update_job(job_id, phase='processing', percent=95, message='Creating ZIP...')
            _zip_folder(job_dir, zip_path)
            shutil.rmtree(job_dir, ignore_errors=True)
            path = zip_path
        else:
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
