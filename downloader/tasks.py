import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings

JOBS = {}
_lock = threading.Lock()


def create_job() -> str:
    job_id = str(uuid.uuid4())
    with _lock:
        JOBS[job_id] = {
            'status': 'queued',
            'phase': 'starting',
            'percent': 0,
            'speed': '',
            'eta': '',
            'message': 'Starting...',
            'filename': None,
            'filepath': None,
            'url': None,
            'error': None,
            'delete_at': None,
        }
    return job_id


def get_job(job_id: str) -> dict | None:
    with _lock:
        job = JOBS.get(job_id)
        return dict(job) if job else None


def update_job(job_id: str, **kwargs):
    with _lock:
        if job_id in JOBS:
            JOBS[job_id].update(kwargs)


def schedule_delete(path: Path):
    secs = getattr(settings, 'FILE_RETENTION_SECONDS', 600)

    def _delete():
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
        for p in path.parent.glob(f"{path.stem}.*"):
            try:
                if p.is_file():
                    p.unlink()
            except OSError:
                pass

    delete_at = datetime.now(timezone.utc).timestamp() + secs
    threading.Timer(secs, _delete).start()
    return delete_at
