import json
import tempfile
import unittest
from pathlib import Path

from kavita_yamtrack_sync.config import load_config
from kavita_yamtrack_sync.review_store import (
    ReviewError,
    approve_candidate,
    approve_manual,
    get_reviews,
    ignore,
    reconsider,
)


class ReviewStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        directory = Path(self.temp.name)
        self.config_path = directory / "config.json"
        self.state_path = directory / "state.json"
        self.review_path = directory / "review.json"
        self.config_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kavita_url": "https://kavita.example.test",
                    "state_file": str(self.state_path),
                    "review_file": str(self.review_path),
                    "accounts": [
                        {
                            "yamtrack_username": "reader",
                            "kavita_api_key_file": "/run/secrets/reader",
                        },
                        {
                            "yamtrack_username": "other",
                            "kavita_api_key_file": "/run/secrets/other",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.review_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "accounts": {
                        "reader": {
                            "chapters": {
                                "7": {
                                    "status": "review",
                                    "signature": {"title": "Ambiguous book"},
                                    "candidates": [
                                        {
                                            "source": "openlibrary",
                                            "media_id": "OL123M",
                                            "title": "Candidate",
                                            "score": 90,
                                        }
                                    ],
                                }
                            }
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        self.config = load_config(self.config_path)

    def tearDown(self):
        self.temp.cleanup()

    def test_approves_only_a_proposed_candidate(self):
        approve_candidate(self.config, "reader", 7, "ol123m")
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        target = state["accounts"]["reader"]["chapters"]["7"]["target"]
        self.assertEqual(
            target,
            {"source": "openlibrary", "media_id": "OL123M", "media_type": "book"},
        )
        self.assertEqual(get_reviews(self.config, "reader").chapters, {})

    def test_approves_hardcover_candidate(self):
        review = json.loads(self.review_path.read_text(encoding="utf-8"))
        review["accounts"]["reader"]["chapters"]["7"]["candidates"] = [
            {
                "source": "hardcover",
                "media_id": "4567",
                "media_type": "book",
                "title": "Candidate",
                "score": 97,
            }
        ]
        self.review_path.write_text(json.dumps(review), encoding="utf-8")
        approve_candidate(self.config, "reader", 7, "4567", "hardcover")
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(
            state["accounts"]["reader"]["chapters"]["7"]["target"],
            {"source": "hardcover", "media_id": "4567", "media_type": "book"},
        )

    def test_rejects_candidate_not_in_users_queue(self):
        with self.assertRaises(ReviewError):
            approve_candidate(self.config, "reader", 7, "OL999M")
        with self.assertRaises(ReviewError):
            approve_candidate(self.config, "other", 7, "OL123M")

    def test_manual_edition_requires_safe_id(self):
        with self.assertRaises(ReviewError):
            approve_manual(self.config, "reader", 7, "https://example.test/")
        approve_manual(self.config, "reader", 7, "OL999M")

    def test_ignore_and_reconsider(self):
        ignore(self.config, "reader", 7)
        self.assertEqual(
            get_reviews(self.config, "reader").chapters["7"]["status"], "ignored"
        )
        reconsider(self.config, "reader", 7)
        self.assertEqual(get_reviews(self.config, "reader").chapters, {})


if __name__ == "__main__":
    unittest.main()
