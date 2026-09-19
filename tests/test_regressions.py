import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request

from kavita_yamtrack_sync.core import KavitaChapter, decide_sync
from kavita_yamtrack_sync.http_clients import (
    JsonClient,
    KavitaClient,
    OpenLibraryClient,
    RemoteError,
    _CatalogRedirects,
    _RejectRedirects,
)
from kavita_yamtrack_sync.matching import infer_identity
from kavita_yamtrack_sync.observability import account_status, healthy, status_path
from kavita_yamtrack_sync.state import save_state


def chapter(**kwargs):
    values = dict(
        chapter_id=1,
        series_id=1,
        title="Book",
        authors=(),
        isbn=None,
        pages_read=199,
        total_pages=200,
        total_reads=0,
        completed=False,
        first_read_at=None,
        last_read_at=None,
    )
    return KavitaChapter(**(values | kwargs))


class RegressionTests(unittest.TestCase):
    def test_incomplete_never_hits_max_including_old_rounded_state(self):
        for maximum in (1, 2, 100, 400):
            for progress in (0, maximum, maximum * 2):
                result = decide_sync(chapter(), maximum, current_progress=progress)
                self.assertLess(result.progress, maximum)
                self.assertEqual(result.status, "In progress")

    def test_unknown_page_count_does_not_invent_percentage(self):
        self.assertEqual(decide_sync(chapter(total_pages=0), None).progress, 0)

    def test_source_volume_variants_and_metadata_precedence(self):
        for name in (
            "Book T03.cbr",
            "Book 3.cbr",
            "Book - Tomo 03.cbr",
            "Book Vol. 3.cbr",
        ):
            result = infer_identity(chapter(file_name=name))
            self.assertEqual((result.title, result.volume), ("Book", 3))
        self.assertEqual(
            infer_identity(chapter(file_name="Book T03.cbr", volume_number="4")).volume,
            4,
        )
        self.assertIsNone(infer_identity(chapter(file_name="1984.epub")).volume)
        self.assertIsNone(infer_identity(chapter(file_name="Summer 1984.epub")).volume)

    def test_public_redirects_bounded_same_origin_only(self):
        req = Request("https://openlibrary.org/isbn/9780306406157.json")
        handler = _CatalogRedirects()
        self.assertIsNotNone(
            handler.redirect_request(
                req, None, 302, "", {}, "https://openlibrary.org/books/OL1M.json"
            )
        )
        for url in (
            "http://openlibrary.org/books/OL1M.json",
            "https://evil.test/a",
            "https://openlibrary.org:444/a",
            "https://user@openlibrary.org/a",
        ):
            self.assertIsNone(handler.redirect_request(req, None, 302, "", {}, url))
        self.assertIsNone(
            _RejectRedirects().redirect_request(
                req, None, 302, "", {}, "https://openlibrary.org/a"
            )
        )

    def test_isbn_not_found_distinct_from_outage_and_unsafe_input(self):
        client = OpenLibraryClient()
        client.http = Mock()
        self.assertIsNone(client.resolve_isbn("../../bad"))
        client.http.request.assert_not_called()
        client.http.request.side_effect = RemoteError("not found", status=404)
        self.assertIsNone(client.resolve_isbn("9780306406157"))
        client.http.request.side_effect = RemoteError("busy", status=503)
        with self.assertRaises(RemoteError):
            client.resolve_isbn("9780306406157")

    @patch("kavita_yamtrack_sync.http_clients.time.sleep")
    def test_retries_transient_get_but_not_auth_and_never_leaks_url(self, sleep):
        for method, expected in [("GET", 3), ("POST", 1)]:
            client = JsonClient()
            client.opener = Mock()
            client.opener.open.side_effect = lambda *a, **k: (_ for _ in ()).throw(
                HTTPError(
                    "https://host/?apiKey=TEST_ONLY", 503, "Unavailable", {}, BytesIO()
                )
            )
            with self.assertRaises(RemoteError) as context:
                client.request(method, "https://host/?apiKey=TEST_ONLY")
            self.assertEqual(client.opener.open.call_count, expected)
            self.assertNotIn("TEST_ONLY", str(context.exception))

    def test_chapter_failure_does_not_abort_remaining_and_cache_avoids_refetch(self):
        client = KavitaClient("https://test.invalid", "fixture")
        client.reading_history = lambda: [
            {"seriesId": 3, "chapters": [{"chapterId": 1}, {"chapterId": 2}]}
        ]
        client.on_deck_series = lambda: []
        calls = []

        def get(path, params):
            key = params["chapterId"]
            calls.append(key)
            if key == 1:
                raise RemoteError("gone", status=404)
            return {"id": key, "pagesRead": 4, "pages": 20}, {}

        client.get = get
        cache = {}
        self.assertEqual(
            [
                c.chapter_id
                for c in client.chapters_with_progress(cache=cache, cache_seconds=3600)
            ],
            [2],
        )
        self.assertEqual(len(client.errors), 1)
        client.chapters_with_progress(cache=cache, cache_seconds=3600)
        self.assertEqual(calls, [1, 2, 1])
        cache["2"]["fetched_at"] = 0
        client.chapters_with_progress(cache=cache, cache_seconds=3600)
        self.assertEqual(calls[-2:], [1, 2])

    def test_on_deck_outage_still_returns_valid_history_chapters(self):
        client = KavitaClient("https://test.invalid", "fixture")
        client.reading_history = lambda: [{"chapters": [{"chapterId": 2}]}]
        client.get = Mock(return_value=({"id": 2, "pagesRead": 4, "pages": 20}, {}))
        client.on_deck_series = Mock(side_effect=RemoteError("busy", status=503))
        result = client.chapters_with_progress()
        self.assertEqual([item.chapter_id for item in result], [2])
        self.assertEqual(client.errors, [{"code": "on_deck_http_503"}])

    def test_authentication_failure_is_not_treated_as_missing_chapter(self):
        client = KavitaClient("https://test.invalid", "fixture")
        client.reading_history = lambda: [{"chapters": [{"chapterId": 1}]}]
        client.get = Mock(side_effect=RemoteError("denied", status=401))
        with self.assertRaises(RemoteError):
            client.chapters_with_progress()

    def test_health_requires_recent_success_and_hides_other_accounts(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = SimpleNamespace(
                state_file=Path(tmp) / "state.json",
                accounts=[SimpleNamespace(yamtrack_username="a")],
                stale_after_seconds=600,
            )
            self.assertFalse(healthy(config, {"status": "ok"}, now=1000))
            self.assertFalse(
                healthy(config, {"status": "ok", "last_success_at": 1}, now=1000)
            )
            self.assertFalse(
                healthy(config, {"status": "partial", "last_success_at": 999}, now=1000)
            )
            self.assertTrue(
                healthy(config, {"status": "ok", "last_success_at": 999}, now=1000)
            )
            save_state(
                status_path(config),
                {
                    "schema_version": 1,
                    "accounts": {"other": {"errors": [{"code": "PRIVATE"}]}},
                },
            )
            self.assertEqual(account_status(config, "other"), {"configured": False})
            self.assertNotIn("PRIVATE", str(account_status(config, "a")))


if __name__ == "__main__":
    unittest.main()
