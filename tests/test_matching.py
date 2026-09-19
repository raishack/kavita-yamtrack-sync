import unittest
from datetime import datetime, timezone

from kavita_yamtrack_sync.core import KavitaChapter, YamtrackTarget
from kavita_yamtrack_sync.matching import (
    EditionCandidate,
    MatchResult,
    RankedCandidate,
    choose_match,
    combine_provider_matches,
    infer_identity,
    query_variants,
    rank_candidates,
)


class MatchingTests(unittest.TestCase):
    def chapter(self, **overrides):
        values = {
            "chapter_id": 7,
            "series_id": 8,
            "title": "Jujutsu Kaisen - Tomo",
            "authors": (),
            "isbn": None,
            "pages_read": 100,
            "total_pages": 192,
            "total_reads": 0,
            "completed": False,
            "first_read_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
            "last_read_at": datetime(2026, 8, 2, tzinfo=timezone.utc),
            "file_name": "Jujutsu Kaisen - Tomo 03 (#018-025).cbr",
            "volume_number": "3",
        }
        values.update(overrides)
        return KavitaChapter(**values)

    def edition(self, media_id, **overrides):
        values = {
            "target": YamtrackTarget("openlibrary", media_id),
            "title": "Jujutsu Kaisen, Vol. 3",
            "authors": ("Gege Akutami",),
            "publishers": (),
            "languages": (),
            "pages": 192,
        }
        values.update(overrides)
        return EditionCandidate(**values)

    def test_infers_title_and_volume_from_cbr_name(self):
        identity = infer_identity(self.chapter())
        self.assertEqual(identity.title, "Jujutsu Kaisen")
        self.assertEqual(identity.volume, 3)

    def test_prefers_unique_spanish_publisher(self):
        identity = infer_identity(self.chapter())
        ranked = rank_candidates(
            identity,
            [
                self.edition("OL-SPA", publishers=("NORMA EDITORIAL, S.A.",)),
                self.edition("OL-ENG", publishers=("VIZ Media LLC",)),
            ],
            ("Norma",),
        )
        result = choose_match(ranked)
        self.assertEqual(result.status, "auto")
        self.assertEqual(result.target.media_id, "OL-SPA")
        self.assertGreaterEqual(ranked[0].score, 95)

    def test_duplicate_high_scores_require_review(self):
        identity = infer_identity(self.chapter())
        ranked = rank_candidates(
            identity,
            [
                self.edition("OL-A", publishers=("Norma",)),
                self.edition("OL-B", publishers=("Norma",)),
            ],
            ("Norma",),
        )
        self.assertEqual(choose_match(ranked).status, "review")

    def test_volume_mismatch_is_not_automatic(self):
        identity = infer_identity(self.chapter())
        ranked = rank_candidates(
            identity,
            [
                self.edition(
                    "OL-WRONG", title="Jujutsu Kaisen, Vol. 4", publishers=("Norma",)
                )
            ],
            ("Norma",),
        )
        self.assertEqual(choose_match(ranked).status, "unmatched")

    def test_understands_bare_and_t_prefixed_volume_titles(self):
        identity = infer_identity(self.chapter())
        ranked = rank_candidates(
            identity,
            [
                self.edition(
                    "OL-SPANISH",
                    title="Jujutsu Kaisen 3",
                    publishers=("NORMA EDITORIAL",),
                ),
                self.edition(
                    "OL-FRENCH",
                    title="Jujutsu Kaisen T03",
                    publishers=("Ki-oon",),
                ),
            ],
            ("Norma",),
        )
        self.assertEqual(ranked[0].edition.target.media_id, "OL-SPANISH")
        self.assertGreaterEqual(ranked[0].score, 95)

    def test_exact_isbn_outweighs_incomplete_metadata(self):
        identity = infer_identity(self.chapter(isbn="9780306406157"))
        ranked = rank_candidates(
            identity,
            [
                self.edition(
                    "HC-ISBN",
                    title="Jujutsu Kaisen 3",
                    target=YamtrackTarget("hardcover", "123"),
                    isbns=("978-0-306-40615-7",),
                )
            ],
            ("Norma",),
        )
        self.assertEqual(choose_match(ranked).status, "auto")

    def test_query_variants_are_bounded_and_start_with_isbn(self):
        identity = infer_identity(self.chapter(isbn="9780306406157"))
        queries = query_variants(identity, ("Jujutsu Kaisen",))
        self.assertEqual(queries[0], "9780306406157")
        self.assertLessEqual(len(queries), 6)

    def test_combines_safe_provider_matches_without_false_ambiguity(self):
        openlibrary = RankedCandidate(self.edition("OL-A"), 101)
        hardcover = RankedCandidate(
            self.edition("HC-A", target=YamtrackTarget("hardcover", "22")),
            100,
        )
        result = combine_provider_matches(
            [
                MatchResult("auto", (openlibrary,)),
                MatchResult("auto", (hardcover,)),
            ],
            preferred_sources=("openlibrary", "hardcover"),
            auto_score=95,
            review_score=80,
            min_margin=8,
        )
        self.assertEqual(result.status, "auto")
        self.assertEqual(result.target.source, "openlibrary")


if __name__ == "__main__":
    unittest.main()
