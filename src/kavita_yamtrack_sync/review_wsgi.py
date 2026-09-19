"""Dedicated WSGI entry point that reuses Yamtrack authentication/session."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("KAVITA_SYNC_CONFIG", "/run/kavita-yamtrack-sync/config.json")

from django.conf import settings  # noqa: E402

settings.ROOT_URLCONF = "kavita_yamtrack_sync.review_urls"
settings.CSRF_FAILURE_VIEW = "kavita_yamtrack_sync.review_views.csrf_failure"

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
