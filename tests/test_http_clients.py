import unittest

from kavita_yamtrack_sync.core import KavitaChapter
from kavita_yamtrack_sync.http_clients import KavitaClient, OpenLibraryClient


class FakeHttp:
    def __init__(self, responder):
        self.responder = responder

    def request(self, method, url, *, headers=None):
        return self.responder(method, url, headers or {})


class HttpClientTests(unittest.TestCase):
    def test_kavita_auth_and_chapter_discovery(self):
        def responder(method, url, headers):
            if "/api/Account/refresh-account" in url:
                return {"token": "jwt", "kavitaVersion": "0.9.0.2"}, {}
            self.assertEqual(headers["Authorization"], "Bearer jwt")
            if "/api/Stats/reading-history?" in url:
                return [
                    {
                        "seriesId": 8,
                        "seriesName": "Example Series",
                        "chapters": [
                            {
                                "chapterId": 7,
                                "startTimeUtc": "2026-08-01T10:00:00Z",
                                "endTimeUtc": "2026-08-01T11:00:00Z",
                                "completed": False,
                            }
                        ],
                    }
                ], {}
            if "/api/Series/on-deck?" in url:
                return [], {}
            if "/api/Chapter?" in url:
                return {
                    "id": 7,
                    "titleName": "Example Book",
                    "pages": 200,
                    "pagesRead": 50,
                    "totalReads": 0,
                    "isbn": "978-0-306-40615-7",
                    "writers": [{"name": "Example Author"}],
                    "files": [{"filePath": "P:/Books/Example Book.epub"}],
                }, {}
            self.fail(f"Unexpected URL: {url}")

        client = KavitaClient("https://kavita.example.test", "secret")
        client.http = FakeHttp(responder)
        client.authenticate()
        chapters = client.chapters_with_progress()

        self.assertEqual(client.server_version, "0.9.0.2")
        self.assertEqual(len(chapters), 1)
        self.assertEqual(chapters[0].chapter_id, 7)
        self.assertEqual(chapters[0].series_id, 8)
        self.assertEqual(chapters[0].isbn, "9780306406157")
        self.assertEqual(chapters[0].authors, ("Example Author",))
        self.assertEqual(chapters[0].file_name, "Example Book.epub")

    def test_discovers_fresh_progress_before_history_aggregation(self):
        def responder(method, url, headers):
            if "/api/Account/refresh-account" in url:
                return {"token": "jwt", "kavitaVersion": "0.9.0.2"}, {}
            self.assertEqual(headers["Authorization"], "Bearer jwt")
            if "/api/Stats/reading-history?" in url:
                return [], {}
            if "/api/Series/on-deck?" in url:
                return [{"id": 8, "name": "Fresh Book"}], {}
            if "/api/Series/metadata?" in url:
                return {"writers": [{"name": "Fresh Author"}]}, {}
            if "/api/Series/volumes?" in url:
                return [
                    {
                        "chapters": [
                            {
                                "id": 7,
                                "titleName": "Fresh Book",
                                "pages": 200,
                                "pagesRead": 25,
                                "totalReads": 0,
                                "isbn": "978-0-306-40615-7",
                            }
                        ]
                    }
                ], {}
            self.fail(f"Unexpected URL: {url}")

        client = KavitaClient("https://kavita.example.test", "secret")
        client.http = FakeHttp(responder)
        client.authenticate()
        chapters = client.chapters_with_progress()

        self.assertEqual(len(chapters), 1)
        self.assertEqual(chapters[0].chapter_id, 7)
        self.assertEqual(chapters[0].pages_read, 25)
        self.assertEqual(chapters[0].authors, ("Fresh Author",))

    def test_openlibrary_resolves_edition(self):
        client = OpenLibraryClient()
        client.http = FakeHttp(
            lambda method, url, headers: ({"key": "/books/OL123M"}, {})
        )
        target = client.resolve_isbn("9780306406157")
        self.assertEqual(target.source, "openlibrary")
        self.assertEqual(target.media_id, "OL123M")

    def test_openlibrary_suggests_unique_preferred_edition(self):
        def responder(method, url, headers):
            if "/search.json?" in url:
                return {
                    "docs": [
                        {
                            "key": "/works/OL-WORK",
                            "title": "Jujutsu Kaisen, Vol. 3",
                            "author_name": ["Gege Akutami"],
                        }
                    ]
                }, {}
            if "/works/OL-WORK/editions.json?" in url:
                return {
                    "entries": [
                        {
                            "key": "/books/OL-SPA",
                            "title": "Jujutsu Kaisen, Vol. 3",
                            "publishers": ["Norma Editorial"],
                            "number_of_pages": 192,
                        },
                        {
                            "key": "/books/OL-ENG",
                            "title": "Jujutsu Kaisen, Vol. 3",
                            "publishers": ["VIZ Media"],
                            "number_of_pages": 192,
                        },
                    ]
                }, {}
            self.fail(f"Unexpected URL: {url}")

        chapter = KavitaChapter(
            chapter_id=3,
            series_id=2,
            title="Jujutsu Kaisen - Tomo",
            authors=(),
            isbn=None,
            pages_read=10,
            total_pages=192,
            total_reads=0,
            completed=False,
            first_read_at=None,
            last_read_at=None,
            file_name="Jujutsu Kaisen - Tomo 03 (#018-025).cbr",
            volume_number="3",
        )
        client = OpenLibraryClient()
        client.http = FakeHttp(responder)
        result = client.suggest(chapter)
        self.assertEqual(result.status, "auto")
        self.assertEqual(result.target.media_id, "OL-SPA")

    def test_openlibrary_rejects_unsafe_manual_edition_before_http(self):
        client = OpenLibraryClient()
        client.http = FakeHttp([])
        self.assertIsNone(client.get_edition("OL../../works/OL1W/M"))


if __name__ == "__main__":
    unittest.main()
