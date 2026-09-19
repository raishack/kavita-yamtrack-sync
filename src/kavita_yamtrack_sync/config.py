"""Strict, secret-file based configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .core import YamtrackTarget


@dataclass(frozen=True)
class AccountConfig:
    yamtrack_username: str
    kavita_api_key_file: Path
    overrides: dict[int, YamtrackTarget] = field(default_factory=dict)


@dataclass(frozen=True)
class Config:
    kavita_url: str
    state_file: Path
    accounts: tuple[AccountConfig, ...]
    timeout_seconds: int = 20
    allow_regress: bool = False
    allowed_kavita_versions: tuple[str, ...] = ("0.9.0.2",)
    allowed_yamtrack_versions: tuple[str, ...] = ("0.26.1", "0.26.3")
    auto_match_min_score: int = 95
    review_match_min_score: int = 80
    auto_match_min_margin: int = 8
    preferred_publishers: tuple[str, ...] = ("Norma",)
    review_file: Path | None = None
    hardcover_enabled: bool = True
    manual_fallback_after_cycles: int = 3
    manual_reconcile_hours: int = 24
    metadata_cache_seconds: int = 3600
    stale_after_seconds: int = 3600


def load_config(path: str | Path) -> Config:
    config_path = Path(path)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1:
        raise ValueError("Unsupported or missing schema_version")

    kavita_url = str(raw["kavita_url"]).rstrip("/")
    _validate_kavita_url(kavita_url)

    accounts: list[AccountConfig] = []
    usernames: set[str] = set()
    for entry in raw.get("accounts", []):
        username = str(entry["yamtrack_username"]).strip()
        if not username or username in usernames:
            raise ValueError("Each Yamtrack username must be non-empty and unique")
        usernames.add(username)

        overrides: dict[int, YamtrackTarget] = {}
        for chapter_id, target in entry.get("overrides", {}).items():
            overrides[int(chapter_id)] = _target(target)

        accounts.append(
            AccountConfig(
                yamtrack_username=username,
                kavita_api_key_file=Path(entry["kavita_api_key_file"]),
                overrides=overrides,
            )
        )

    if not accounts:
        raise ValueError("At least one account mapping is required")

    state_file = Path(raw["state_file"])
    review_file = Path(raw.get("review_file") or state_file.with_name("review.json"))
    auto_score = int(raw.get("auto_match_min_score", 95))
    review_score = int(raw.get("review_match_min_score", 80))
    margin = int(raw.get("auto_match_min_margin", 8))
    if not 0 <= review_score <= auto_score <= 110 or not 0 <= margin <= 110:
        raise ValueError("Invalid automatic matching thresholds")

    return Config(
        kavita_url=kavita_url,
        state_file=state_file,
        accounts=tuple(accounts),
        timeout_seconds=max(5, min(120, int(raw.get("timeout_seconds", 20)))),
        allow_regress=bool(raw.get("allow_regress", False)),
        allowed_kavita_versions=_versions(raw, "allowed_kavita_versions", ("0.9.0.2",)),
        allowed_yamtrack_versions=_versions(
            raw, "allowed_yamtrack_versions", ("0.26.1", "0.26.3")
        ),
        auto_match_min_score=auto_score,
        review_match_min_score=review_score,
        auto_match_min_margin=margin,
        preferred_publishers=tuple(
            str(value).strip()
            for value in raw.get("preferred_publishers", ["Norma"])
            if str(value).strip()
        ),
        review_file=review_file,
        hardcover_enabled=bool(raw.get("hardcover_enabled", True)),
        manual_fallback_after_cycles=max(
            1, min(96, int(raw.get("manual_fallback_after_cycles", 3)))
        ),
        metadata_cache_seconds=max(
            0, min(86400, int(raw.get("metadata_cache_seconds", 3600)))
        ),
        stale_after_seconds=max(
            600, min(86400, int(raw.get("stale_after_seconds", 3600)))
        ),
        manual_reconcile_hours=max(
            1, min(24 * 30, int(raw.get("manual_reconcile_hours", 24)))
        ),
    )


def read_api_key(path: Path) -> str:
    if path.stat().st_mode & 0o077:
        raise ValueError(f"API key file permissions are too broad: {path}")
    key = path.read_text(encoding="utf-8").strip()
    if not key:
        raise ValueError(f"API key file is empty: {path}")
    return key


def _target(raw: dict[str, Any]) -> YamtrackTarget:
    source = str(raw.get("source", "openlibrary")).strip()
    media_id = str(raw["media_id"]).strip()
    if not source or not media_id:
        raise ValueError("Override source and media_id must be non-empty")
    return YamtrackTarget(source=source, media_id=media_id)


def _versions(
    raw: dict[str, Any], key: str, default: tuple[str, ...]
) -> tuple[str, ...]:
    versions = tuple(str(value).strip().lstrip("v") for value in raw.get(key, default))
    if not versions or any(not value for value in versions):
        raise ValueError(f"{key} must contain at least one valid version")
    return versions


def _validate_kavita_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme == "https" and parsed.hostname:
        return
    if parsed.scheme == "http" and parsed.hostname:
        try:
            address = ip_address(parsed.hostname)
        except ValueError:
            pass
        else:
            if address.is_private and not address.is_loopback:
                return
    raise ValueError("kavita_url must use HTTPS or HTTP to an explicit private IP")
