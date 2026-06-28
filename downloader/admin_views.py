import json
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods


def admin_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.session.get('is_admin'):
            return redirect('admin_login')
        return view(request, *args, **kwargs)
    return wrapper


def _list_files():
    d = settings.DOWNLOAD_DIR
    d.mkdir(parents=True, exist_ok=True)
    files = []
    for p in sorted(d.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if not p.is_file():
            continue
        st = p.stat()
        files.append({
            'name': p.name,
            'size': st.st_size,
            'size_mb': round(st.st_size / 1_048_576, 2),
            'modified': datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime('%Y-%m-%d %H:%M'),
        })
    return files


def _safe_path(name: str) -> Path | None:
    path = (settings.DOWNLOAD_DIR / Path(name).name).resolve()
    if not str(path).startswith(str(settings.DOWNLOAD_DIR.resolve())):
        return None
    return path


@require_http_methods(['GET', 'POST'])
def admin_login(request):
    if request.session.get('is_admin'):
        return admin_panel(request)
    error = ''
    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        if code == settings.ADMIN_CODE:
            request.session['is_admin'] = True
            return admin_panel(request)
        error = 'Invalid code'
    return render(request, 'admin.html', {'error': error, 'logged_in': False})


@admin_required
@require_http_methods(['GET'])
def admin_panel(request):
    files = _list_files()
    total = sum(f['size'] for f in files)
    return render(request, 'admin.html', {
        'logged_in': True,
        'files': files,
        'total_mb': round(total / 1_048_576, 2),
        'count': len(files),
    })


@admin_required
@require_http_methods(['POST'])
def admin_delete(request):
    try:
        data = json.loads(request.body)
        name = data.get('name', '')
        path = _safe_path(name)
        if not path or not path.exists():
            return JsonResponse({'error': 'File not found'}, status=404)
        path.unlink()
        return JsonResponse({'ok': True})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@admin_required
@require_http_methods(['POST'])
def admin_delete_all(request):
    deleted = 0
    for f in _list_files():
        path = _safe_path(f['name'])
        if path and path.exists():
            path.unlink()
            deleted += 1
    return JsonResponse({'ok': True, 'deleted': deleted})


def admin_logout(request):
    request.session.flush()
    return redirect('admin_login')
