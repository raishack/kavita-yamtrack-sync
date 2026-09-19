import unittest
from datetime import datetime, timezone

from kavita_yamtrack_sync.automation import (
    manual_target,
    next_reconcile_at,
    pending_action,
    reconciliation_due,
)
from kavita_yamtrack_sync.core import KavitaChapter


class AutomationTests(unittest.TestCase):
    def chapter(self):
        return KavitaChapter(
            chapter_id=7,
            series_id=8,
            title="Example",
            authors=(),
            isbn=None,
            pages_read=10,
            total_pages=100,
            total_reads=0,
            completed=False,
            first_read_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            last_read_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )

    def test_manual_target_is_stable_per_user_and_chapter(self):
        first = manual_target("reader", self.chapter())
        second = manual_target("reader", self.chapter())
        other = manual_target("other", self.chapter())
        self.assertEqual(first, second)
        self.assertNotEqual(first.media_id, other.media_id)
        self.assertEqual(first.source, "manual")

    def test_reconciliation_schedule_is_deterministic(self):
        scheduled = next_reconcile_at(24, now=100)
        self.assertEqual(scheduled, 86500)
        self.assertFalse(
            reconciliation_due({"next_reconcile_at": scheduled}, now=86499)
        )
        self.assertTrue(reconciliation_due({"next_reconcile_at": scheduled}, now=86500))
        self.assertTrue(reconciliation_due({}, now=100))

    def test_pending_items_fall_back_but_ignored_items_do_not(self):
        self.assertEqual(pending_action("review", 1, 3), ("cached", 2))
        self.assertEqual(pending_action("review", 2, 3), ("manual", 3))
        self.assertEqual(pending_action("ignored", 99, 3), ("ignored", 99))


if __name__ == "__main__":
    unittest.main()
