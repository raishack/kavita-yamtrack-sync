import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sync_test_settings")
import django

django.setup()
from django.test.runner import DiscoverRunner

raise SystemExit(
    bool(DiscoverRunner(verbosity=2).run_tests(["/audit/tests/integration"]))
)
