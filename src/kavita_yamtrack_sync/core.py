"""Pure synchronization rules, independent from Django and HTTP."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

COMPLETED = "Completed"
IN_PROGRESS = "In progress"


@dataclass(frozen=True)
class KavitaChapter:
    """The subset of Kavita chapter/progress data needed by the sync."""

    chapter_id: int
    series_id: int
    title: str
    authors: tuple[str, ...]
    isbn: str | None
    pages_read: int
    total_pages: int
    total_reads: int
    completed: bool
    first_read_at: datetime | None
    last_read_at: datetime | None
    file_name: str = ""
    volume_number: str = ""


@dataclass(frozen=True)
class YamtrackTarget:
    """Stable Yamtrack provider identity."""

    source: str
    media_id: str
    media_type: str = "book"


@dataclass(frozen=True)
class SyncDecision:
    """Desired Yamtrack state for a Kavita chapter."""

    status: str
    progress: int
    start_date: datetime | None
    end_date: datetime | None

    @property
    def signature(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "progress": self.progress,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
        }


def parse_datetime(value: str | None) -> datetime | None:
    """Parse Kavita ISO-8601 values without discarding timezone information."""

    if not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)


def normalize_isbn(value: str | None) -> str | None:
    """Return a validated ISBN-10/13, or ``None`` for unsafe identifiers."""

    if not value:
        return None
    isbn = re.sub(r"[^0-9Xx]", "", value).upper()
    if len(isbn) == 10 and _valid_isbn10(isbn):
        return isbn
    if len(isbn) == 13 and _valid_isbn13(isbn):
        return isbn
    return None


def _valid_isbn10(isbn: str) -> bool:
    if not isbn[:9].isdigit() or not (isbn[9].isdigit() or isbn[9] == "X"):
        return False
    values = [int(char) for char in isbn[:9]] + [10 if isbn[9] == "X" else int(isbn[9])]
    return sum((10 - index) * value for index, value in enumerate(values)) % 11 == 0


def _valid_isbn13(isbn: str) -> bool:
    if not isbn.isdigit():
        return False
    weighted = sum(
        int(char) * (1 if index % 2 == 0 else 3) for index, char in enumerate(isbn[:12])
    )
    check = (10 - weighted % 10) % 10
    return check == int(isbn[12])


def chapter_ids_from_history(history: Iterable[dict[str, Any]]) -> set[int]:
    """Collect chapter IDs from Kavita reading-session responses."""

    chapter_ids: set[int] = set()
    for session in history:
        for chapter in session.get("chapters") or []:
            chapter_id = chapter.get("chapterId")
            if isinstance(chapter_id, int) and chapter_id > 0:
                chapter_ids.add(chapter_id)
    return chapter_ids


def history_bounds(
    history: Iterable[dict[str, Any]], chapter_id: int
) -> tuple[datetime | None, datetime | None, bool]:
    """Return the first/last read time and whether a session completed a chapter."""

    starts: list[datetime] = []
    ends: list[datetime] = []
    completed = False
    for session in history:
        for chapter in session.get("chapters") or []:
            if chapter.get("chapterId") != chapter_id:
                continue
            start = parse_datetime(
                chapter.get("startTimeUtc") or session.get("startTimeUtc")
            )
            end = parse_datetime(chapter.get("endTimeUtc") or session.get("endTimeUtc"))
            if start:
                starts.append(start)
            if end:
                ends.append(end)
            completed = completed or bool(chapter.get("completed"))
    return (min(starts) if starts else None, max(ends) if ends else None, completed)


def decide_sync(
    chapter: KavitaChapter,
    yamtrack_max_progress: int | None,
    *,
    current_progress: int = 0,
    current_status: str | None = None,
    allow_regress: bool = False,
) -> SyncDecision | None:
    """Map Kavita page progress to Yamtrack while failing closed on regressions."""

    finished = (
        chapter.completed
        or chapter.total_reads > 0
        or (chapter.total_pages > 0 and chapter.pages_read >= chapter.total_pages)
    )
    if not finished and chapter.pages_read <= 0:
        return None

    max_progress = max(0, int(yamtrack_max_progress or 0))
    if finished:
        status = COMPLETED
        progress = max_progress if max_progress else max(0, current_progress)
        end_date = chapter.last_read_at
    else:
        status = IN_PROGRESS
        if max_progress and chapter.total_pages > 0:
            ratio = min(1.0, max(0.0, chapter.pages_read / chapter.total_pages))
            progress = min(max_progress - 1, max(1, round(max_progress * ratio)))
        else:
            progress = max(0, current_progress)
        end_date = None

    if not allow_regress:
        if current_status == COMPLETED:
            status = COMPLETED
            progress = max(progress, current_progress)
            end_date = end_date or chapter.last_read_at
        else:
            progress = max(progress, current_progress)

    # Clamp after the anti-regression rule too: old rounded values must not
    # accidentally trigger Yamtrack's automatic completion in Book.save().
    if max_progress:
        progress = min(
            progress, max_progress if status == COMPLETED else max_progress - 1
        )

    return SyncDecision(
        status=status,
        progress=progress,
        start_date=chapter.first_read_at,
        end_date=end_date,
    )
