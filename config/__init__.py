# Load the Celery app when Django starts so @shared_task uses it. Guarded so the
# site still runs if Celery isn't installed (background jobs just won't run).
try:
    from .celery import app as celery_app

    __all__ = ('celery_app',)
except ImportError:  # pragma: no cover
    celery_app = None
