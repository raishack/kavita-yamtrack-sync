import unittest
from datetime import datetime, timezone

from kavita_yamtrack_sync.core import (
    COMPLETED,
    IN_PROGRESS,
    KavitaChapter,
    chapter_ids_from_history,
    decide_sync,
    history_bounds,
    normalize_isbn,
)


class CoreTests(unittest.TestCase):
    def chapter(self, **overrides):
        values = {
            "chapter_id": 10,
            "series_id": 20,
            "title": "Example",
            "authors": ("Author",),
            "isbn": "9780306406157",
            "pages_read": 50,
            "total_pages": 200,
            "total_reads": 0,
            "completed": False,
            "first_read_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
            "last_read_at": datetime(2026, 8, 2, tzinfo=timezone.utc),
        }
        values.update(overrides)
        return KavitaChapter(**values)

    def test_validates_isbn(self):
        self.assertEqual(normalize_isbn("978-0-306-40615-7"), "9780306406157")
        self.assertEqual(normalize_isbn("0-306-40615-2"), "0306406152")
        self.assertIsNone(normalize_isbn("9780306406158"))

    def test_maps_percentage_to_yamtrack_pages(self):
        decision = decide_sync(self.chapter(), 400)
        self.assertEqual(decision.status, IN_PROGRESS)
        self.assertEqual(decision.progress, 100)
        self.assertIsNone(decision.end_date)

    def test_completed_sets_max_progress_and_end_date(self):
        chapter = self.chapter(completed=True)
        decision = decide_sync(chapter, 400)
        self.assertEqual(decision.status, COMPLETED)
        self.assertEqual(decision.progress, 400)
        self.assertEqual(decision.end_date, chapter.last_read_at)

    def test_does_not_regress_completed_item(self):
        decision = decide_sync(
            self.chapter(pages_read=10),
            400,
            current_progress=400,
            current_status=COMPLETED,
        )
        self.assertEqual(decision.status, COMPLETED)
        self.assertEqual(decision.progress, 400)

    def test_zero_progress_is_skipped(self):
        self.assertIsNone(decide_sync(self.chapter(pages_read=0), 400))

    def test_extracts_history_bounds(self):
        history = [
            {
                "chapters": [
                    {
                        "chapterId": 10,
                        "startTimeUtc": "2026-08-01T10:00:00Z",
                        "endTimeUtc": "2026-08-01T10:30:00Z",
                        "completed": False,
                    }
                ]
            },
            {
                "chapters": [
                    {
                        "chapterId": 10,
                        "startTimeUtc": "2026-08-02T10:00:00Z",
                        "endTimeUtc": "2026-08-02T11:00:00Z",
                        "completed": True,
                    },
                    {"chapterId": 11},
                ]
            },
        ]
        self.assertEqual(chapter_ids_from_history(history), {10, 11})
        first, last, completed = history_bounds(history, 10)
        self.assertEqual(first, datetime(2026, 8, 1, 10, tzinfo=timezone.utc))
        self.assertEqual(last, datetime(2026, 8, 2, 11, tzinfo=timezone.utc))
        self.assertTrue(completed)


if __name__ == "__main__":
    unittest.main()
