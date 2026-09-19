"""Safe mutations for human-reviewed Kavita/Open Library matches."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import Config
from .locking import FileLock
from .state import load_state, save_state

OPENLIBRARY_EDITION = re.compile(r"^OL\d+M$")


class ReviewError(ValueError):
    pass


@dataclass(frozen=True)
class ReviewSnapshot:
    username: str
    chapters: dict[str, dict]


def get_reviews(config: Config, username: str) -> ReviewSnapshot:
    review = load_state(config.review_file)
    account = review.get("accounts", {}).get(username, {})
    chapters = account.get("chapters", {}) if isinstance(account, dict) else {}
    return ReviewSnapshot(
        username=username, chapters=chapters if isinstance(chapters, dict) else {}
    )


def approve_candidate(
    config: Config,
    username: str,
    chapter_id: int,
    media_id: str,
    source: str | None = None,
) -> None:
    with FileLock(_lock_path(config)):
        state, review, pending = _load_pending(config, username, chapter_id)
        allowed = [
            candidate
            for candidate in pending.get("candidates", [])
            if isinstance(candidate, dict)
        ]
        selected = next(
            (
                candidate
                for candidate in allowed
                if str(candidate.get("media_id", "")).casefold()
                == str(media_id).strip().casefold()
                and (source is None or str(candidate.get("source", "")) == source)
            ),
            None,
        )
        if selected is None:
            raise ReviewError("The selected edition is not in the review candidates")
        selected_source = str(selected.get("source") or "openlibrary")
        normalized = _provider_id(selected_source, selected.get("media_id", ""))
        _approve(
            state,
            review,
            config,
            username,
            chapter_id,
            pending,
            normalized,
            selected_source,
            str(selected.get("media_type") or "book"),
        )


def approve_manual(
    config: Config, username: str, chapter_id: int, media_id: str
) -> None:
    normalized = _edition_id(media_id)
    with FileLock(_lock_path(config)):
        state, review, pending = _load_pending(config, username, chapter_id)
        _approve(
            state,
            review,
            config,
            username,
            chapter_id,
            pending,
            normalized,
            "openlibrary",
            "book",
        )


def ignore(config: Config, username: str, chapter_id: int) -> None:
    with FileLock(_lock_path(config)):
        _, review, pending = _load_pending(config, username, chapter_id)
        pending["status"] = "ignored"
        save_state(config.review_file, review)


def reconsider(config: Config, username: str, chapter_id: int) -> None:
    with FileLock(_lock_path(config)):
        _, review, _ = _load_pending(config, username, chapter_id)
        chapters = review["accounts"][username]["chapters"]
        chapters.pop(str(chapter_id), None)
        save_state(config.review_file, review)


def _approve(
    state,
    review,
    config,
    username,
    chapter_id,
    pending,
    media_id,
    source,
    media_type,
):
    account_state = state["accounts"].setdefault(username, {"chapters": {}})
    chapters = account_state.setdefault("chapters", {})
    previous = chapters.get(str(chapter_id), {})
    chapters[str(chapter_id)] = {
        **previous,
        "target": {
            "source": source,
            "media_id": media_id,
            "media_type": media_type,
        },
        "match_signature": pending.get("signature", {}),
        "reviewed": True,
    }
    if (
        previous.get("target")
        and previous["target"] != chapters[str(chapter_id)]["target"]
    ):
        chapters[str(chapter_id)]["previous_target"] = (
            previous.get("previous_target") or previous["target"]
        )
    chapters[str(chapter_id)].pop("retry", None)
    review["accounts"][username]["chapters"].pop(str(chapter_id), None)
    # Save the approved target first. If the process stops between writes, the
    # next sync still has the safe target and merely leaves a stale queue row.
    save_state(config.state_file, state)
    save_state(config.review_file, review)


def _load_pending(config: Config, username: str, chapter_id: int):
    state = load_state(config.state_file)
    review = load_state(config.review_file)
    account = review.get("accounts", {}).get(username)
    chapters = account.get("chapters") if isinstance(account, dict) else None
    pending = chapters.get(str(chapter_id)) if isinstance(chapters, dict) else None
    if not isinstance(pending, dict):
        raise ReviewError("This review item no longer exists")
    return state, review, pending


def _edition_id(value: str) -> str:
    normalized = str(value).strip().upper()
    if not OPENLIBRARY_EDITION.fullmatch(normalized):
        raise ReviewError("Open Library edition IDs must look like OL123M")
    return normalized


def _provider_id(source: str, value: str) -> str:
    if source == "openlibrary":
        return _edition_id(value)
    if source == "hardcover":
        normalized = str(value).strip()
        if not normalized.isdigit():
            raise ReviewError("Hardcover IDs must be numeric")
        return normalized
    raise ReviewError("Unsupported review provider")


def _lock_path(config: Config):
    return config.state_file.with_name("sync.lock")
