"""Offline UI fixtures. No authentication, real accounts or database reads."""

import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sync_test_settings")
import django
from django.template import Context, Engine

django.setup()
root = Path("/evidence")
template = Engine().from_string(
    Path("/audit/src/kavita_yamtrack_sync/review.html").read_text()
)
base = {
    "request": SimpleNamespace(user=SimpleNamespace(username="Test reader")),
    "messages": [],
    "csrf_token": "offline-ui-fixture",
    "pending_count": 0,
    "ignored_count": 0,
    "chapters": [],
}
healthy = dict(
    configured=True,
    healthy=True,
    status="ok",
    last_success=datetime(2026, 9, 6, 12, tzinfo=timezone.utc),
    duration=8.2,
    manual=2,
    errors=[],
)
for name, status in [
    ("healthy", healthy),
    ("unconfigured", {"configured": False}),
    (
        "partial",
        healthy
        | {
            "healthy": False,
            "status": "partial",
            "errors": [
                {
                    "chapter_id": 42,
                    "message": "Another reading already exists for this edition. Both entries were preserved; review the migration.",
                }
            ],
        },
    ),
]:
    data = base | {"sync": status}
    if name == "partial":
        data["pending_count"] = 1
        data["chapters"] = [
            {
                "chapter_id": 42,
                "status": "review",
                "signature": {
                    "title": "A test book to review",
                    "file_name": "A test book V03.cbr",
                    "pages": 200,
                },
                "candidates": [
                    {
                        "source": "openlibrary",
                        "media_id": "OL123M",
                        "title": "A test book · Volume 3",
                        "score": 90,
                        "pages": 200,
                        "publishers": ["Test Publisher"],
                        "url": "https://openlibrary.org/books/OL123M",
                    }
                ],
            }
        ]
    (root / f"panel-{name}.html").write_text(template.render(Context(data)))
