"""Shared task-attachment validation - used by both the web team board
views (employees/views.py) and the mobile team board API
(employees/mobile_teams_api.py), so it lives here rather than in either
one (importing from the huge views.py into a small mobile API module
risks import-order issues; this module has no Django app dependencies of
its own beyond the TaskAttachment.Kind choices)."""
from .models import TaskAttachment

TASK_ATTACHMENT_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}
TASK_ATTACHMENT_VIDEO_TYPES = {'video/mp4', 'video/webm', 'video/quicktime'}
TASK_ATTACHMENT_MAX_IMAGE_SIZE = 8 * 1024 * 1024   # 8MB
TASK_ATTACHMENT_MAX_VIDEO_SIZE = 30 * 1024 * 1024  # 30MB, "a short video"


def validate_task_attachment_upload(upload):
    """Returns (kind, None) on success, or (None, error_message) on failure."""
    content_type = (upload.content_type or '').lower()
    if content_type in TASK_ATTACHMENT_IMAGE_TYPES:
        kind, max_size = TaskAttachment.Kind.IMAGE, TASK_ATTACHMENT_MAX_IMAGE_SIZE
    elif content_type in TASK_ATTACHMENT_VIDEO_TYPES:
        kind, max_size = TaskAttachment.Kind.VIDEO, TASK_ATTACHMENT_MAX_VIDEO_SIZE
    else:
        return None, 'Only images (JPG/PNG/GIF/WEBP) or short videos (MP4/WEBM/MOV) can be attached.'
    if upload.size > max_size:
        limit_mb = max_size // (1024 * 1024)
        return None, f'File is too large - keep it under {limit_mb}MB.'
    return kind, None
