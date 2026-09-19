"""Pure scheduling decisions for zero-touch fallback and reconciliation."""

from __future__ import annotations

import time
import uuid

from .core import KavitaChapter, YamtrackTarget


def pending_action(status: str, cycles: int, fallback_after: int) -> tuple[str, int]:
    """Return ignored, cached or manual for an unchanged pending match."""

    if status == "ignored":
        return "ignored", max(1, int(cycles))
    next_cycle = max(1, int(cycles)) + 1
    if next_cycle >= int(fallback_after):
        return "manual", next_cycle
    return "cached", next_cycle


def manual_target(username: str, chapter: KavitaChapter) -> YamtrackTarget:
    media_id = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"kavita-yamtrack:{username}:{chapter.series_id}:{chapter.chapter_id}",
    )
    return YamtrackTarget(source="manual", media_id=str(media_id))


def reconciliation_due(saved: dict, *, now: int | None = None) -> bool:
    current = int(time.time()) if now is None else int(now)
    try:
        return int(saved.get("next_reconcile_at", 0)) <= current
    except (AttributeError, TypeError, ValueError):
        return True


def next_reconcile_at(hours: int, *, now: int | None = None) -> int:
    current = int(time.time()) if now is None else int(now)
    return current + int(hours) * 3600
