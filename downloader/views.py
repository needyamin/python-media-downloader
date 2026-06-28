import json
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.http import FileResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .services import ffmpeg_available, get_media_info, start_download_job, _friendly_error, _deno_available
from .tasks import get_job


def index(request):
    return render(request, 'index.html', {'ffmpeg': ffmpeg_available()})


@csrf_exempt
@require_http_methods(['GET'])
def health(request):
    import yt_dlp
    return JsonResponse({
        'ok': True,
        'ffmpeg': ffmpeg_available(),
        'deno': _deno_available(),
        'yt_dlp': yt_dlp.version.__version__,
    })


@csrf_exempt
@require_http_methods(['POST'])
def get_info(request):
    try:
        data = json.loads(request.body or '{}')
        url = (data.get('url') or '').strip()
        if not url:
            return JsonResponse({'error': 'URL required'}, status=400)
        return JsonResponse(get_media_info(url))
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid request'}, status=400)
    except Exception as e:
        return JsonResponse({'error': _friendly_error(e)}, status=400)


@csrf_exempt
@require_http_methods(['POST'])
def download(request):
    try:
        data = json.loads(request.body)
        url = data.get('url', '').strip()
        fmt = data.get('format', 'best')
        live_from_start = bool(data.get('live_from_start', False))
        if not url:
            return JsonResponse({'error': 'URL required'}, status=400)
        task_id = start_download_job(url, fmt, live_from_start)
        return JsonResponse({'task_id': task_id})
    except Exception as e:
        return JsonResponse({'error': _friendly_error(e)}, status=400)


@require_http_methods(['GET'])
def job_status(request, task_id):
    job = get_job(task_id)
    if not job:
        return JsonResponse({'error': 'Task not found'}, status=404)
    return JsonResponse(job)


def serve_file(request, task_id):
    job = get_job(task_id)
    if not job or job.get('status') != 'done':
        return JsonResponse({'error': 'File not found'}, status=404)
    path = Path(job.get('filepath', ''))
    if not path.exists():
        return JsonResponse({'error': 'File not found or expired'}, status=404)
    filename = job.get('filename') or path.name
    response = FileResponse(open(path, 'rb'), as_attachment=True)
    response['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote(filename)}"
    return response
