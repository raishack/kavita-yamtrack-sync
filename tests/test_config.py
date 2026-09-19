import json
import tempfile
import unittest
from pathlib import Path

from kavita_yamtrack_sync.config import load_config


class ConfigTests(unittest.TestCase):
    def test_loads_strict_config_and_override(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "kavita_url": "https://kavita.example.test/",
                        "state_file": "/data/state.json",
                        "accounts": [
                            {
                                "yamtrack_username": "reader",
                                "kavita_api_key_file": "/run/secrets/reader",
                                "overrides": {
                                    "12": {"source": "openlibrary", "media_id": "OL1M"}
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            config = load_config(path)
            self.assertEqual(config.kavita_url, "https://kavita.example.test")
            self.assertEqual(config.accounts[0].overrides[12].media_id, "OL1M")
            self.assertTrue(config.hardcover_enabled)
            self.assertEqual(config.manual_fallback_after_cycles, 3)
            self.assertEqual(config.manual_reconcile_hours, 24)

    def test_rejects_plain_http(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "kavita_url": "http://kavita.example.test",
                        "state_file": "/data/state.json",
                        "accounts": [
                            {
                                "yamtrack_username": "reader",
                                "kavita_api_key_file": "/run/secrets/reader",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_config(path)

    def test_allows_plain_http_to_explicit_private_ip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "kavita_url": "http://10.20.30.40:5000/",
                        "state_file": "/data/state.json",
                        "accounts": [
                            {
                                "yamtrack_username": "reader",
                                "kavita_api_key_file": "/run/secrets/reader",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            config = load_config(path)
            self.assertEqual(config.kavita_url, "http://10.20.30.40:5000")

    def test_rejects_plain_http_to_loopback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "kavita_url": "http://127.0.0.1:5000",
                        "state_file": "/data/state.json",
                        "accounts": [
                            {
                                "yamtrack_username": "reader",
                                "kavita_api_key_file": "/run/secrets/reader",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
