import os
import tempfile
import time
from dataclasses import replace
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from app.management.commands.sync_kavita import (
    Command,
    SyncConflict,
    _identity_matches,
    _match_signature,
    _state_record,
)
from app.models import Book, Item
from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.test import Client, TestCase

from kavita_yamtrack_sync.automation import reconciliation_due
from kavita_yamtrack_sync.config import AccountConfig, Config
from kavita_yamtrack_sync.core import KavitaChapter, YamtrackTarget
from kavita_yamtrack_sync.http_clients import RemoteError
from kavita_yamtrack_sync.observability import status_path
from kavita_yamtrack_sync.review_store import approve_manual
from kavita_yamtrack_sync.state import load_state, save_state


def chapter(**changes):
    return KavitaChapter(
        **(
            dict(
                chapter_id=1,
                series_id=1,
                title="Fixture book",
                authors=(),
                isbn=None,
                pages_read=100,
                total_pages=200,
                total_reads=0,
                completed=False,
                first_read_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                last_read_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            )
            | changes
        )
    )


class SyncORMTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.user = get_user_model().objects.create(username="reader")
        self.target = YamtrackTarget("openlibrary", "OL123M")
        self.manual = YamtrackTarget("manual", "00000000-0000-0000-0000-000000000001")
        self.fetch = patch.object(Item, "fetch_releases", return_value=None).start()
        self.addCleanup(patch.stopall)
        self.metadata = patch(
            "app.providers.services.get_media_metadata",
            side_effect=lambda kind, mid, source: {
                "title": "Fixture book",
                "image": "",
                "max_progress": 0 if source == "manual" else 100,
            },
        ).start()
        self.config = Config(
            kavita_url="https://kavita.invalid",
            state_file=Path(self.tmp.name) / "state.json",
            review_file=Path(self.tmp.name) / "review.json",
            accounts=(
                AccountConfig("reader", Path(self.tmp.name) / "key", {1: self.target}),
            ),
            hardcover_enabled=False,
        )

    def sync(self, c=None, target=None, **kwargs):
        return Command._sync_chapter(
            self.user,
            c or chapter(),
            target or self.target,
            allow_regress=False,
            apply_changes=True,
            **kwargs,
        )

    def book(self, target, **fields):
        item = Item.objects.create(
            media_id=target.media_id,
            source=target.source,
            media_type="book",
            title="Fixture",
            image="",
        )
        return Book.objects.create(
            item=item, user=self.user, status="In progress", **fields
        )

    def run_sync(self, clients=None, apply=True):
        command = Command(stdout=StringIO(), stderr=StringIO())
        client = Mock(server_version="0.9.0.2", errors=[])
        client.chapters_with_progress.return_value = [chapter()]
        with (
            patch(
                "app.management.commands.sync_kavita.load_config",
                return_value=self.config,
            ),
            patch(
                "app.management.commands.sync_kavita.read_api_key",
                return_value="fixture",
            ),
            patch(
                "app.management.commands.sync_kavita.KavitaClient",
                side_effect=clients if clients else None,
                return_value=client,
            ),
            patch.dict(os.environ, VERSION="0.26.3"),
        ):
            command.handle(config="unused", apply=apply, refresh_matches=False)
        return command

    def test_actual_book_save_does_not_complete_early(self):
        self.sync(chapter(pages_read=199))
        book = Book.objects.get()
        self.assertEqual(
            (book.progress, book.status, book.end_date), (99, "In progress", None)
        )

    def test_one_page_edition_stays_in_progress_at_zero(self):
        self.metadata.side_effect = lambda *args: {
            "title": "One",
            "image": "",
            "max_progress": 1,
        }
        self.sync(chapter(pages_read=199))
        self.assertEqual(
            (Book.objects.get().progress, Book.objects.get().status), (0, "In progress")
        )

    def test_migrate_scales_progress_preserves_pk_notes_score_history(self):
        book = self.book(self.manual, progress=200, notes="Keep this", score=7)
        history_count = book.history.count()
        saved = {"media_pk": book.pk, "max_progress": 400}
        self.sync(
            chapter(pages_read=200, total_pages=400),
            previous_target=self.manual,
            saved=saved,
        )
        book.refresh_from_db()
        self.assertEqual(Book.objects.count(), 1)
        self.assertEqual(
            (book.item.media_id, book.progress, book.notes, book.score),
            ("OL123M", 50, "Keep this", 7),
        )
        self.assertGreaterEqual(book.history.count(), history_count)
        self.assertEqual(saved["media_pk"], book.pk)

    def test_collision_preserves_both_readings_without_reassigning(self):
        self.book(self.manual, progress=20, notes="manual notes")
        other = self.book(self.target, progress=30, notes="canonical notes")
        before = list(Book.objects.values("id", "item_id", "progress", "notes"))
        with self.assertRaisesRegex(
            SyncConflict, "existing_reading_migration_conflict"
        ):
            self.sync(previous_target=self.manual)
        self.assertEqual(
            list(Book.objects.values("id", "item_id", "progress", "notes")), before
        )
        self.assertEqual(Book.objects.filter(item=other.item).count(), 1)

    def test_effective_dates_idempotence_and_no_new_history(self):
        old = datetime(2020, 1, 1, tzinfo=timezone.utc)
        book = self.book(self.target, progress=50, start_date=old)
        count = book.history.count()
        for _ in range(2):
            decision, changed = self.sync()
            self.assertFalse(changed)
            self.assertEqual(decision.start_date, old)
        self.assertEqual(book.history.count(), count)

    def test_completed_user_date_not_overwritten_by_reread(self):
        old = datetime(2020, 1, 2, tzinfo=timezone.utc)
        book = self.book(self.target, progress=100, end_date=old)
        book.refresh_from_db()
        self.assertEqual(book.status, "Completed")
        initial_end = book.end_date
        self.sync(chapter(completed=True))
        book.refresh_from_db()
        self.assertEqual(book.end_date, initial_end)
        self.assertEqual(book.progress, 100)

    def test_deleted_bound_reading_is_not_recreated(self):
        with self.assertRaisesRegex(SyncConflict, "reading_deleted_or_replaced"):
            self.sync(saved={"media_pk": 99999})
        self.assertEqual(Book.objects.count(), 0)

    def test_orm_side_effect_mismatch_rolls_back_item_and_book(self):
        self.metadata.side_effect = [
            {"title": "Test", "image": "", "max_progress": 100},
            {"max_progress": 40},
            {"max_progress": 40},
        ]
        with self.assertRaisesRegex(SyncConflict, "orm_changed_requested_progress"):
            self.sync()
        self.assertEqual(Book.objects.count(), 0)
        self.assertEqual(Item.objects.count(), 0)

    def test_manual_reconciliation_expires_despite_unchanged_cycles(self):
        decision, _ = self.sync(target=self.manual)
        saved = {}
        due_times = []
        for hour in range(0, 49):
            now = 1000 + hour * 3600
            due = bool(saved) and reconciliation_due(saved, now=now)
            if due:
                due_times.append(hour)
            with patch("kavita_yamtrack_sync.automation.time.time", return_value=now):
                saved = _state_record(
                    self.manual, decision, self.config, saved, reconciled=due
                )
        self.assertEqual(due_times, [24, 48])

    def test_command_persists_success_and_second_apply_is_idempotent(self):
        self.run_sync()
        first = list(Book.objects.values())
        history = Book.objects.get().history.count()
        self.run_sync()
        self.assertEqual(list(Book.objects.values()), first)
        self.assertEqual(Book.objects.get().history.count(), history)
        self.assertEqual(load_state(status_path(self.config))["status"], "ok")

    def test_dry_run_does_not_write_db_or_state(self):
        self.run_sync(apply=False)
        self.assertEqual(Book.objects.count(), 0)
        self.assertFalse(self.config.state_file.exists())
        self.assertFalse(status_path(self.config).exists())

    def test_one_bad_account_does_not_block_another(self):
        get_user_model().objects.create(username="other")
        self.config = replace(
            self.config,
            accounts=(AccountConfig("other", Path("/unused")), *self.config.accounts),
        )
        failed = Mock()
        failed.authenticate.side_effect = RemoteError("denied", status=401)
        good = Mock(server_version="0.9.0.2", errors=[])
        good.chapters_with_progress.return_value = [chapter()]
        with self.assertRaises(CommandError):
            self.run_sync([failed, good])
        self.assertEqual(Book.objects.get().user, self.user)
        health = load_state(status_path(self.config))
        self.assertEqual(health["accounts"]["reader"]["status"], "ok")
        self.assertEqual(health["accounts"]["other"]["status"], "failed")
        self.assertEqual(health["status"], "partial")

    def test_one_provider_failure_does_not_block_next_book_and_is_checkpointed(self):
        from app.providers.services import ProviderAPIError

        self.assert_provider_error_isolated(
            ProviderAPIError('openlibrary', RuntimeError('private provider payload'))
        )

    def test_async_provider_connection_failure_isolated(self):
        from aiohttp import ClientConnectionError

        self.assert_provider_error_isolated(ClientConnectionError('private request URL'))

    def test_requests_provider_connection_failure_isolated(self):
        from requests import ConnectionError

        self.assert_provider_error_isolated(ConnectionError('private request URL'))

    def assert_provider_error_isolated(self, provider_error):
        target2 = YamtrackTarget("openlibrary", "OL456M")
        self.config = replace(
            self.config,
            accounts=(
                replace(
                    self.config.accounts[0], overrides={1: self.target, 2: target2}
                ),
            ),
        )
        client = Mock(server_version="0.9.0.2", errors=[])
        client.chapters_with_progress.return_value = [chapter(), chapter(chapter_id=2)]
        original = self.metadata.side_effect

        def metadata(kind, mid, source):
            if mid == "OL123M":
                raise provider_error
            return original(kind, mid, source)

        self.metadata.side_effect = metadata
        with self.assertRaises(CommandError) as error:
            self.run_sync([client])
        self.assertNotIn("private", str(error.exception))
        self.assertEqual(Book.objects.get().item.media_id, "OL456M")
        state = load_state(self.config.state_file)["accounts"]["reader"]["chapters"]
        self.assertIn("retry", state["1"])
        self.assertIn("media_pk", state["2"])

    def test_incompatible_kavita_aborts_before_any_book_write(self):
        client = Mock(server_version="unvalidated")
        with self.assertRaisesRegex(CommandError, "incompatible_kavita_version"):
            self.run_sync([client])
        self.assertEqual(Book.objects.count(), 0)

    def test_ignored_item_precedes_isbn_and_survives_fingerprint_upgrade(self):
        c = chapter(isbn="9780306406157")
        previous = _match_signature(c)
        previous.pop("isbn")
        previous.pop("series_id")
        review = {"1": {"status": "ignored", "signature": previous}}
        provider = Mock()
        summary = {"skipped": 0}
        Command()._process_chapter(
            self.user,
            c,
            replace(self.config.accounts[0], overrides={}),
            self.config,
            {},
            {},
            {},
            review,
            provider,
            summary,
            {"apply": True, "refresh_matches": True},
        )
        provider.resolve_isbn.assert_not_called()
        self.assertEqual(summary["skipped"], 1)

    def test_manual_approval_keeps_previous_target_for_safe_migration(self):
        previous = {
            "target": {
                "source": "manual",
                "media_id": self.manual.media_id,
                "media_type": "book",
            },
            "media_pk": 7,
            "max_progress": 400,
        }
        save_state(
            self.config.state_file,
            {
                "schema_version": 1,
                "accounts": {"reader": {"chapters": {"1": previous}}},
            },
        )
        save_state(
            self.config.review_file,
            {
                "schema_version": 1,
                "accounts": {
                    "reader": {
                        "chapters": {
                            "1": {
                                "status": "review",
                                "signature": _match_signature(chapter()),
                            }
                        }
                    }
                },
            },
        )
        approve_manual(self.config, "reader", 1, "OL123M")
        saved = load_state(self.config.state_file)["accounts"]["reader"]["chapters"][
            "1"
        ]
        self.assertEqual(saved["previous_target"], previous["target"])
        self.assertEqual(saved["media_pk"], 7)

    def test_sparse_metadata_does_not_invalidate_learned_identity(self):
        prior = _match_signature(chapter(authors=("Author",)))
        sparse = _match_signature(chapter())
        self.assertTrue(_identity_matches(prior, sparse))
        decision, _ = self.sync()
        result = _state_record(
            self.target,
            decision,
            self.config,
            {"match_signature": prior},
            match_signature=sparse,
        )
        self.assertEqual(result["match_signature"]["authors"], ["Author"])

    def test_changed_identity_stops_before_provider_and_preserves_book(self):
        self.config = replace(
            self.config, accounts=(replace(self.config.accounts[0], overrides={}),)
        )
        saved = {
            "target": {"source": "openlibrary", "media_id": "OL123M"},
            "match_signature": _match_signature(chapter(title="Old title")),
        }
        reviews = {}
        provider = Mock()
        with self.assertRaisesRegex(SyncConflict, "identity_changed"):
            Command()._process_chapter(
                self.user,
                chapter(),
                self.config.accounts[0],
                self.config,
                saved,
                {},
                {},
                reviews,
                provider,
                {},
                {"apply": True, "refresh_matches": False},
            )
        provider.resolve_isbn.assert_not_called()
        self.assertEqual(reviews["1"]["status"], "identity_changed")
        self.assertEqual(Book.objects.count(), 0)

    def test_metadata_outage_does_not_create_manual_fallback(self):
        self.config = replace(
            self.config, accounts=(replace(self.config.accounts[0], overrides={}),)
        )
        client = Mock(server_version="0.9.0.2", errors=[])
        client.chapters_with_progress.return_value = [chapter(isbn="9780306406157")]
        with patch("app.management.commands.sync_kavita.OpenLibraryClient") as factory:
            factory.return_value.resolve_isbn.side_effect = RemoteError(
                "busy", status=503
            )
            with self.assertRaises(CommandError):
                self.run_sync([client])
        self.assertEqual(Book.objects.count(), 0)
        self.assertFalse(
            load_state(self.config.review_file)["accounts"]["reader"]["chapters"]
        )

    def test_approved_book_applies_after_review_without_duplicate(self):
        self.config = replace(
            self.config, accounts=(replace(self.config.accounts[0], overrides={}),)
        )
        save_state(
            self.config.review_file,
            {
                "schema_version": 1,
                "accounts": {
                    "reader": {
                        "chapters": {
                            "1": {
                                "status": "review",
                                "signature": _match_signature(chapter()),
                            }
                        }
                    }
                },
            },
        )
        approve_manual(self.config, "reader", 1, "OL123M")
        self.run_sync()
        self.run_sync()
        self.assertEqual(Book.objects.count(), 1)
        self.assertTrue(
            load_state(self.config.state_file)["accounts"]["reader"]["chapters"]["1"][
                "reviewed"
            ]
        )

    def test_another_users_valid_csrf_cannot_modify_my_review(self):
        import kavita_yamtrack_sync.review_views as views

        other = get_user_model().objects.create(username="not-linked")
        review = {
            "schema_version": 1,
            "accounts": {
                "reader": {
                    "chapters": {
                        "1": {
                            "status": "review",
                            "signature": _match_signature(chapter()),
                            "candidates": [],
                        }
                    }
                }
            },
        }
        save_state(self.config.review_file, review)
        client = Client(enforce_csrf_checks=True)
        client.force_login(other)
        from django.middleware.csrf import _get_new_csrf_string

        token = _get_new_csrf_string()
        client.cookies["csrftoken"] = token
        with patch.object(views, "_config", return_value=self.config):
            self.assertContains(client.get("/kavita-sync/"), "aún no está conectada")
            response = client.post("/kavita-sync/1/ignore/", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(load_state(self.config.review_file), review)

    def test_web_auth_csrf_account_isolation_and_real_readiness(self):
        import kavita_yamtrack_sync.review_views as views

        with patch.object(views, "_config", return_value=self.config):
            client = Client(enforce_csrf_checks=True)
            self.assertEqual(client.get("/kavita-sync/").status_code, 302)
            self.assertEqual(client.get("/kavita-sync/health/").status_code, 200)
            self.assertEqual(client.get("/kavita-sync/ready/").status_code, 503)
            client.force_login(self.user)
            save_state(
                status_path(self.config),
                {
                    "schema_version": 1,
                    "status": "ok",
                    "last_success_at": int(time.time()),
                    "accounts": {
                        "reader": {"status": "ok", "last_success_at": int(time.time())},
                        "other": {"errors": [{"code": "OTHER_PRIVATE"}]},
                    },
                },
            )
            response = client.get("/kavita-sync/")
            self.assertContains(response, "Sincronización al día")
            self.assertNotContains(response, "OTHER_PRIVATE")
            if os.environ.get("KAVITA_SYNC_QA_OUTPUT"):
                Path(
                    os.environ["KAVITA_SYNC_QA_OUTPUT"], "panel-healthy.html"
                ).write_bytes(response.content)
            self.assertEqual(client.get("/kavita-sync/ready/").status_code, 200)
            self.assertEqual(client.post("/kavita-sync/1/ignore/").status_code, 403)
