"""Safely pull Kavita book progress into Yamtrack using Yamtrack's ORM."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import replace

from aiohttp import ClientError
from app.models import Item, MediaTypes, Sources, Status
from app.providers import services
from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, OperationalError, transaction
from requests import RequestException

from kavita_yamtrack_sync.automation import (
    manual_target,
    next_reconcile_at,
    pending_action,
    reconciliation_due,
)
from kavita_yamtrack_sync.config import load_config, read_api_key
from kavita_yamtrack_sync.core import YamtrackTarget, decide_sync
from kavita_yamtrack_sync.http_clients import (
    KavitaClient,
    OpenLibraryClient,
    RemoteError,
)
from kavita_yamtrack_sync.locking import FileLock
from kavita_yamtrack_sync.matching import (
    EditionCandidate,
    candidate_for_target,
    choose_match,
    combine_provider_matches,
    infer_identity,
    query_variants,
    rank_candidates,
)
from kavita_yamtrack_sync.observability import (
    ProviderLogFilter,
    error_code,
    status_path,
)
from kavita_yamtrack_sync.state import load_state, save_state


class Command(BaseCommand):
    help = "Pull per-user book progress from Kavita into Yamtrack"

    def add_arguments(self, parser):
        parser.add_argument(
            "--config", required=True, help="Path to the JSON config file"
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist changes. Without this flag the command is a dry run.",
        )
        parser.add_argument(
            "--refresh-matches",
            action="store_true",
            help="Re-query Open Library for items already waiting for review.",
        )

    def handle(self, *args, **options):
        config = load_config(options["config"])
        apply_changes = bool(options["apply"])
        with FileLock(config.state_file.with_name("sync.lock"), timeout=60):
            state = load_state(config.state_file)
            review = load_state(config.review_file)
            health = load_state(status_path(config))
            started = int(time.time())
            health.update(started_at=started, status="running", error=None)
            if apply_changes:
                save_state(status_path(config), health)
            provider_logger = logging.getLogger("app.providers.services")
            provider_filter = ProviderLogFilter()
            provider_logger.addFilter(provider_filter)
            try:
                self._run(config, state, review, health, options)
            except Exception as error:
                health.update(
                    status="partial" if health.get("status") == "partial" else "failed",
                    error=error_code(error),
                )
                # Provider exceptions may embed request URLs; never echo them.
                raise CommandError(f"Kavita sync failed: {error_code(error)}") from None
            finally:
                provider_logger.removeFilter(provider_filter)
                health.update(
                    finished_at=int(time.time()),
                    duration_seconds=round(time.time() - started, 2),
                )
                if apply_changes:
                    save_state(status_path(config), health)

    def _run(self, config, state, review, health, options):
        apply_changes = bool(options["apply"])
        version = str(os.environ.get("VERSION", "")).strip().lstrip("v")
        if version not in config.allowed_yamtrack_versions:
            raise CommandError("incompatible_yamtrack_version")
        summary = dict.fromkeys(
            (
                "updated",
                "unchanged",
                "auto_matched",
                "manual_fallback",
                "reconciled",
                "review",
                "unmatched",
                "skipped",
                "errors",
            ),
            0,
        )
        # Version preflight before changing any user's books.
        clients = {}
        for account in config.accounts:
            try:
                client = KavitaClient(
                    config.kavita_url,
                    read_api_key(account.kavita_api_key_file),
                    config.timeout_seconds,
                )
                client.authenticate()
            except (OSError, ValueError, RemoteError) as error:
                clients[account.yamtrack_username] = error
                continue
            if client.server_version not in config.allowed_kavita_versions:
                raise CommandError("incompatible_kavita_version")
            clients[account.yamtrack_username] = client
        openlibrary = OpenLibraryClient(config.timeout_seconds)
        for account in config.accounts:
            username = account.yamtrack_username
            account_state = state["accounts"].setdefault(username, {})
            chapter_state = account_state.setdefault("chapters", {})
            series_state = account_state.setdefault("series", {})
            review_chapters = (
                review["accounts"].setdefault(username, {}).setdefault("chapters", {})
            )
            status = health["accounts"].setdefault(username, {})
            status.update(status="running", started_at=int(time.time()), errors=[])
            try:
                client = clients[username]
                if isinstance(client, Exception):
                    raise client
                user = get_user_model().objects.get(username=username)
                chapters = client.chapters_with_progress(
                    cache=account_state.setdefault("discovery_cache", {}),
                    cache_seconds=config.metadata_cache_seconds,
                )
                status["errors"].extend(client.errors)
                for chapter in chapters:
                    key = str(chapter.chapter_id)
                    saved = chapter_state.get(key, {})
                    retry = saved.get("retry", {})
                    if (
                        not options["refresh_matches"]
                        and retry.get("after", 0) > time.time()
                    ):
                        status["errors"].append(
                            {
                                "chapter_id": chapter.chapter_id,
                                "code": retry.get("code", "retry_pending"),
                            }
                        )
                        continue
                    try:
                        self._process_chapter(
                            user,
                            chapter,
                            account,
                            config,
                            saved,
                            chapter_state,
                            series_state,
                            review_chapters,
                            openlibrary,
                            summary,
                            options,
                        )
                        if key in chapter_state:
                            chapter_state[key].pop("retry", None)
                    except (
                        ClientError,
                        RequestException,
                        RemoteError,
                        services.ProviderAPIError,
                        SyncConflict,
                        ValueError,
                        KeyError,
                        TypeError,
                        IntegrityError,
                        OperationalError,
                    ) as error:
                        code = error_code(error)
                        count = min(8, int(retry.get("count", 0)) + 1)
                        saved["retry"] = {
                            "count": count,
                            "after": int(time.time())
                            + min(3600, 300 * 2 ** (count - 1)),
                            "code": code,
                        }
                        chapter_state[key] = saved
                        status["errors"].append(
                            {"chapter_id": chapter.chapter_id, "code": code}
                        )
                    finally:
                        if apply_changes:
                            # Each committed ORM item is checkpointed before moving on.
                            save_state(config.state_file, state)
                            save_state(config.review_file, review)
                status["status"] = "partial" if status["errors"] else "ok"
                if not status["errors"]:
                    status["last_success_at"] = int(time.time())
            except (
                OSError,
                ValueError,
                RemoteError,
                get_user_model().DoesNotExist,
            ) as error:
                status.update(status="failed", errors=[{"code": error_code(error)}])
            status.update(
                finished_at=int(time.time()),
                pending=sum(
                    r.get("status") != "ignored" for r in review_chapters.values()
                ),
                manual=sum(
                    (r.get("target") or {}).get("source") == "manual"
                    for r in chapter_state.values()
                ),
            )
            summary["errors"] += len(status["errors"])
            if apply_changes:
                save_state(config.state_file, state)
                save_state(config.review_file, review)
                save_state(status_path(config), health)
        health.update(status="partial" if summary["errors"] else "ok", summary=summary)
        if not summary["errors"]:
            health["last_success_at"] = int(time.time())
        self.stdout.write(
            f"Kavita sync {'applied' if apply_changes else 'dry-run'}: {summary}"
        )
        if summary["errors"]:
            # systemd/monitoring must not report success for partial failure.
            raise CommandError("partial_failure_see_status")

    def _process_chapter(
        self,
        user,
        chapter,
        account,
        config,
        saved,
        chapter_state,
        series_state,
        review_chapters,
        openlibrary,
        summary,
        options,
    ):
        apply_changes = bool(options["apply"])
        key = str(chapter.chapter_id)
        signature = _match_signature(chapter)
        pending = review_chapters.get(key, {})
        # Human exclusions take priority over ISBN and every automatic path.
        if pending.get("status") == "ignored" and _identity_matches(
            pending.get("signature"), signature
        ):
            summary["skipped"] += 1
            return
        saved_target = _saved_target(saved)
        override = account.overrides.get(chapter.chapter_id)
        if (
            saved_target
            and saved.get("match_signature")
            and not _identity_matches(saved["match_signature"], signature)
            and override is None
        ):
            review_chapters[key] = {
                "status": "identity_changed",
                "signature": signature,
                "candidates": [],
            }
            raise SyncConflict("identity_changed_review_required")
        target = override or saved_target
        previous = (
            _saved_target({"target": saved.get("previous_target")}) or saved_target
        )
        manual = (
            saved_target
            if saved_target and saved_target.source == Sources.MANUAL.value
            else None
        )
        reconcile = (
            manual is not None
            and not override
            and (options["refresh_matches"] or reconciliation_due(saved))
        )
        if reconcile:
            target = None
        matched_candidate = None
        profile = series_state.setdefault(str(chapter.series_id), {})
        if target is None and chapter.isbn:
            target = openlibrary.resolve_isbn(chapter.isbn)
        if target is None:
            if (
                manual is None
                and not options["refresh_matches"]
                and _identity_matches(pending.get("signature"), signature)
                and pending.get("status") in {"review", "unmatched"}
            ):
                action, cycles = pending_action(
                    pending["status"],
                    pending.get("cycles", 1),
                    config.manual_fallback_after_cycles,
                )
                if action == "manual":
                    target = manual_target(account.yamtrack_username, chapter)
                    summary["manual_fallback"] += 1
                else:
                    pending["cycles"] = cycles
                    summary[pending["status"]] += 1
                    return
            if target is None:
                match = self._suggest_match(chapter, openlibrary, config, profile)
                matched_candidate = candidate_for_target(match, match.target)
                target = match.target
                if target:
                    summary["auto_matched"] += 1
                elif manual:
                    target = manual
                else:
                    review_chapters[key] = _review_record(
                        chapter, signature, match, cycles=1
                    )
                    summary[match.status] += 1
                    return
        result = self._sync_chapter(
            user,
            chapter,
            target,
            allow_regress=config.allow_regress,
            apply_changes=apply_changes,
            previous_target=previous,
            saved=saved,
        )
        if result is None:
            summary["skipped"] += 1
            return
        decision, changed = result
        summary["updated" if changed else "unchanged"] += 1
        if apply_changes:
            chapter_state[key] = _state_record(
                target,
                decision,
                config,
                saved,
                reconciled=reconcile,
                match_signature=signature,
            )
            review_chapters.pop(key, None)
            _learn_series(profile, chapter, target, matched_candidate)
        if manual and target.source != Sources.MANUAL.value:
            summary["reconciled"] += 1

    def _suggest_match(self, chapter, openlibrary, config, profile):
        preferred_publishers = tuple(
            dict.fromkeys(
                (*config.preferred_publishers, *profile.get("publishers", []))
            )
        )
        preferred_sources = tuple(
            dict.fromkeys(
                (
                    *([profile["source"]] if profile.get("source") else []),
                    Sources.OPENLIBRARY.value,
                    Sources.HARDCOVER.value,
                )
            )
        )
        title_aliases = tuple(profile.get("title_aliases", []))
        matches = [
            openlibrary.suggest(
                chapter,
                preferred_publishers=preferred_publishers,
                preferred_sources=preferred_sources,
                title_aliases=title_aliases,
                auto_score=config.auto_match_min_score,
                review_score=config.review_match_min_score,
                min_margin=config.auto_match_min_margin,
            )
        ]
        if config.hardcover_enabled:
            matches.append(
                self._hardcover_match(
                    chapter,
                    preferred_publishers,
                    preferred_sources,
                    title_aliases,
                    config,
                )
            )
        return combine_provider_matches(
            matches,
            preferred_sources=preferred_sources,
            auto_score=config.auto_match_min_score,
            review_score=config.review_match_min_score,
            min_margin=config.auto_match_min_margin,
        )

    @staticmethod
    def _hardcover_match(
        chapter,
        preferred_publishers,
        preferred_sources,
        title_aliases,
        config,
    ):
        identity = infer_identity(chapter)
        candidates: dict[str, EditionCandidate] = {}
        for query in query_variants(identity, title_aliases)[:4]:
            response = services.search(
                MediaTypes.BOOK.value,
                query,
                1,
                source=Sources.HARDCOVER.value,
            )
            for result in response.get("results", [])[:5]:
                media_id = str(result.get("media_id") or "")
                if not media_id or media_id in candidates:
                    continue
                metadata = services.get_media_metadata(
                    MediaTypes.BOOK.value,
                    media_id,
                    Sources.HARDCOVER.value,
                )
                details = metadata.get("details") or {}
                authors = details.get("author") or []
                if isinstance(authors, str):
                    authors = [authors]
                isbns = details.get("isbn") or []
                if isinstance(isbns, str):
                    isbns = [isbns]
                publisher = details.get("publisher")
                candidates[media_id] = EditionCandidate(
                    target=YamtrackTarget(
                        source=Sources.HARDCOVER.value,
                        media_id=media_id,
                    ),
                    title=str(metadata.get("title") or result.get("title") or ""),
                    authors=tuple(str(value) for value in authors if value),
                    publishers=(str(publisher),) if publisher else (),
                    pages=max(0, int(metadata.get("max_progress") or 0)),
                    isbns=tuple(str(value) for value in isbns if value),
                    image=str(metadata.get("image") or result.get("image") or ""),
                    source_url=str(metadata.get("source_url") or ""),
                )
                if len(candidates) >= 8:
                    break
            if len(candidates) >= 8:
                break
        ranked = rank_candidates(
            identity,
            list(candidates.values()),
            preferred_publishers,
            preferred_sources,
        )
        return choose_match(
            ranked,
            auto_score=config.auto_match_min_score,
            review_score=config.review_match_min_score,
            min_margin=config.auto_match_min_margin,
        )

    @staticmethod
    @transaction.atomic
    def _sync_chapter(
        user,
        chapter,
        target,
        *,
        allow_regress,
        apply_changes,
        previous_target=None,
        saved=None,
    ):
        saved = saved if saved is not None else {}
        if target.source not in {
            Sources.OPENLIBRARY.value,
            Sources.HARDCOVER.value,
            Sources.MANUAL.value,
        }:
            raise CommandError(f"Unsupported Yamtrack source: {target.source}")

        if target.source == Sources.MANUAL.value:
            identity = infer_identity(chapter)
            title = identity.title
            if identity.volume is not None:
                title += f" · Tomo {identity.volume}"
            metadata = {
                "title": title,
                "image": settings.IMG_NONE,
                "max_progress": chapter.total_pages,
            }
        else:
            metadata = services.get_media_metadata(
                MediaTypes.BOOK.value,
                target.media_id,
                target.source,
            )
        item_defaults = {"title": metadata["title"], "image": metadata["image"]}
        item = Item.objects.filter(
            media_id=target.media_id,
            source=target.source,
            media_type=MediaTypes.BOOK.value,
        ).first()
        model = apps.get_model(app_label="app", model_name=MediaTypes.BOOK.value)
        canonical_media = (
            model.objects.select_for_update()
            .filter(user=user, item=item)
            .order_by("-created_at")
            .first()
            if item is not None
            else None
        )
        previous_media = None
        if previous_target is not None and previous_target != target:
            previous_item = Item.objects.filter(
                media_id=previous_target.media_id,
                source=previous_target.source,
                media_type=MediaTypes.BOOK.value,
            ).first()
            if previous_item is not None:
                previous_media = (
                    model.objects.select_for_update()
                    .filter(user=user, item=previous_item)
                    .order_by("-created_at")
                    .first()
                )
        migrating = previous_media is not None and previous_target != target
        if migrating and canonical_media is not None:
            # A second reading may contain independent notes, score or history.
            # Never merge/delete it silently or create a duplicate canonical row.
            raise SyncConflict("existing_reading_migration_conflict")
        media = previous_media if migrating else canonical_media
        if saved.get("media_pk") and (media is None or media.pk != saved["media_pk"]):
            raise SyncConflict("reading_deleted_or_replaced")
        current_progress = media.progress if media else 0
        if migrating:
            old_max = saved.get("max_progress")
            if not old_max and previous_target.source == Sources.MANUAL.value:
                old_max = chapter.total_pages
            if current_progress and not old_max:
                raise SyncConflict("unknown_previous_page_scale")
            new_max = max(0, int(metadata.get("max_progress") or 0))
            current_progress = (
                round(current_progress / old_max * new_max)
                if old_max and new_max
                else 0
            )
        decision = decide_sync(
            chapter,
            metadata.get("max_progress"),
            current_progress=current_progress,
            current_status=media.status if media else None,
            allow_regress=allow_regress,
        )
        if decision is None:
            return None

        # Compare and persist the same effective dates. Preserve user dates on
        # already completed books instead of replacing them with a later reread.
        start_date = (media.start_date if media else None) or decision.start_date
        end_date = decision.end_date
        if media and media.status == Status.COMPLETED.value and not allow_regress:
            end_date = media.end_date or end_date
        decision = replace(decision, start_date=start_date, end_date=end_date)
        changed = (
            migrating
            or media is None
            or any(
                (
                    media.status != decision.status,
                    media.progress != decision.progress,
                    media.start_date != decision.start_date,
                    media.end_date != decision.end_date,
                )
            )
        )
        if apply_changes and media and not changed:
            saved.update(
                media_pk=media.pk, max_progress=metadata.get("max_progress") or 0
            )
        if not changed or not apply_changes:
            return decision, changed

        with transaction.atomic():
            if item is None:
                item, _ = Item.objects.get_or_create(
                    media_id=target.media_id,
                    source=target.source,
                    media_type=MediaTypes.BOOK.value,
                    defaults=item_defaults,
                )
            if migrating:
                previous_media.item = item
                media = previous_media
            if media is None:
                media = model(item=item, user=user)
            media.status = decision.status
            media.progress = decision.progress
            if decision.start_date is not None:
                media.start_date = media.start_date or decision.start_date
            if decision.end_date is not None:
                media.end_date = decision.end_date
            elif media.status != Status.COMPLETED.value:
                media.end_date = None
            media.save()
            if (media.status, media.progress, media.start_date, media.end_date) != (
                decision.status,
                decision.progress,
                decision.start_date,
                decision.end_date,
            ):
                raise SyncConflict("orm_changed_requested_progress")
            saved.update(
                media_pk=media.pk, max_progress=metadata.get("max_progress") or 0
            )
        return decision, True


def _saved_target(saved: dict) -> YamtrackTarget | None:
    target = saved.get("target") if isinstance(saved, dict) else None
    if (
        not isinstance(target, dict)
        or not target.get("source")
        or not target.get("media_id")
    ):
        return None
    return YamtrackTarget(
        source=str(target["source"]),
        media_id=str(target["media_id"]),
        media_type=str(target.get("media_type") or MediaTypes.BOOK.value),
    )


class SyncConflict(ValueError):
    """A non-destructive stop requiring an explicit reading/identity decision."""


def _state_record(
    target, decision, config, previous, *, reconciled=False, match_signature=None
):
    record = dict(previous) if isinstance(previous, dict) else {}
    record.update(
        target={
            "source": target.source,
            "media_id": target.media_id,
            "media_type": target.media_type,
        },
        signature=decision.signature,
    )
    record.pop("previous_target", None)
    record.pop("retry", None)
    if match_signature is not None:
        prior_signature = record.get("match_signature", {})
        record["match_signature"] = {
            key: value or prior_signature.get(key, value)
            for key, value in match_signature.items()
        }
    if target.source == Sources.MANUAL.value:
        if reconciled or not record.get("next_reconcile_at"):
            record["next_reconcile_at"] = next_reconcile_at(
                config.manual_reconcile_hours
            )
        if reconciled:
            record["last_reconcile_at"] = int(time.time())
    else:
        record.pop("next_reconcile_at", None)
    return record


def _learn_series(profile, chapter, target, candidate):
    if target.source == Sources.MANUAL.value:
        return
    identity = infer_identity(chapter)
    aliases = list(profile.get("title_aliases", []))
    for value in (identity.title, chapter.title):
        value = " ".join(str(value).split())
        if value and value not in aliases:
            aliases.append(value)
    publishers = list(profile.get("publishers", []))
    if candidate is not None:
        for value in candidate.edition.publishers:
            if value and value not in publishers:
                publishers.append(value)
    profile.update(
        {
            "source": target.source,
            "title_aliases": aliases[:8],
            "publishers": publishers[:8],
        }
    )


def _match_signature(chapter) -> dict:
    return {
        "title": chapter.title,
        "file_name": chapter.file_name,
        "authors": list(chapter.authors),
        "pages": chapter.total_pages,
        "volume_number": chapter.volume_number,
        "isbn": chapter.isbn,
        "series_id": chapter.series_id,
    }


def _review_record(chapter, signature: dict, match, *, cycles: int) -> dict:
    return {
        "status": match.status,
        "cycles": cycles,
        "signature": signature,
        "candidates": [
            {
                "source": candidate.edition.target.source,
                "media_id": candidate.edition.target.media_id,
                "media_type": candidate.edition.target.media_type,
                "title": candidate.edition.title,
                "publishers": list(candidate.edition.publishers),
                "pages": candidate.edition.pages,
                "score": candidate.score,
                "url": (
                    candidate.edition.source_url
                    or (
                        f"https://openlibrary.org/books/{candidate.edition.target.media_id}"
                        if candidate.edition.target.source == Sources.OPENLIBRARY.value
                        else "https://hardcover.app/"
                    )
                ),
            }
            for candidate in match.candidates
        ],
    }


def _identity_matches(previous, current):
    # Upgrade old fingerprints without invalidating human exclusions merely
    # because the connector learned additional fingerprint fields.
    return bool(previous) and all(
        not current.get(k) or current.get(k) == v for k, v in previous.items()
    )
