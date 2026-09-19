from config.settings import *

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
ROOT_URLCONF = "kavita_yamtrack_sync.review_urls"
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
CELERY_TASK_ALWAYS_EAGER = True
TESTING = False
LOGGING = {"version": 1, "disable_existing_loggers": True}

CSRF_FAILURE_VIEW = "kavita_yamtrack_sync.review_views.csrf_failure"
