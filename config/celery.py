"""Celery app for background jobs (scheduled WhatsApp reports, retries).

Run alongside the web server, in two more terminals (Windows needs --pool=solo):

    celery -A config worker -l info --pool=solo -Q ams
    celery -A config beat -l info

This app uses its OWN Redis database (CELERY_BROKER_URL, default db 5) and its
OWN queue name ('ams'), so it never picks up tasks from anything else that
happens to share the same Redis server.
"""
import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('ams')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
