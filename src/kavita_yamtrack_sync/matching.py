"""Conservative title/volume matching for books without ISBN metadata."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from .core import KavitaChapter, YamtrackTarget


@dataclass(frozen=True)
class BookIdentity:
    title: str
    volume: int | None
    authors: tuple[str, ...]
    pages: int
    isbn: str | None = None


@dataclass(frozen=True)
class EditionCandidate:
    target: YamtrackTarget
    title: str
    authors: tuple[str, ...] = ()
    publishers: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    pages: int = 0
    isbns: tuple[str, ...] = ()
    image: str = ""
    source_url: str = ""


@dataclass(frozen=True)
class RankedCandidate:
    edition: EditionCandidate
    score: int


@dataclass(frozen=True)
class MatchResult:
    status: str
    candidates: tuple[RankedCandidate, ...]

    @property
    def target(self) -> YamtrackTarget | None:
        return self.candidates[0].edition.target if self.status == "auto" else None


def candidate_for_target(
    match: MatchResult | None,
    target: YamtrackTarget | None,
) -> RankedCandidate | None:
    if match is None or target is None:
        return None
    return next(
        (
            candidate
            for candidate in match.candidates
            if candidate.edition.target.source == target.source
            and candidate.edition.target.media_id == target.media_id
        ),
        None,
    )


def combine_provider_matches(
    matches: list[MatchResult],
    *,
    preferred_sources: tuple[str, ...],
    auto_score: int,
    review_score: int,
    min_margin: int,
) -> MatchResult:
    """Choose an already-safe provider match without treating providers as duplicates."""

    ranked: list[RankedCandidate] = []
    automatic: list[RankedCandidate] = []
    seen: set[tuple[str, str]] = set()
    for match in matches:
        for candidate in match.candidates:
            key = (candidate.edition.target.source, candidate.edition.target.media_id)
            if key not in seen:
                seen.add(key)
                ranked.append(candidate)
        selected = candidate_for_target(match, match.target)
        if selected is not None:
            automatic.append(selected)

    source_order = {source: index for index, source in enumerate(preferred_sources)}

    def ordering(candidate):
        return (
            -candidate.score,
            source_order.get(candidate.edition.target.source, 999),
            candidate.edition.target.media_id,
        )

    if automatic:
        chosen = sorted(automatic, key=ordering)[0]
        ordered = [chosen] + [candidate for candidate in ranked if candidate != chosen]
        return MatchResult(status="auto", candidates=tuple(ordered[:6]))

    return choose_match(
        tuple(sorted(ranked, key=ordering)),
        auto_score=auto_score,
        review_score=review_score,
        min_margin=min_margin,
    )


_VOLUME = re.compile(r"\b(?:tomo|vol(?:umen|ume)?|v)\s*[._-]*\s*0*(\d+)\b", re.I)
_TRAILING_VOLUME = re.compile(r"(?:\bT\s*0*|\s+)\s*(\d{1,3})\s*$", re.I)
_ISSUES = re.compile(r"\s*\(?#\d+(?:[-–]\d+)?\)?\s*$")


def infer_identity(chapter: KavitaChapter) -> BookIdentity:
    raw = chapter.file_name.rsplit(".", 1)[0] if chapter.file_name else chapter.title
    raw = _ISSUES.sub("", raw).strip()
    match = _volume_match(raw)
    metadata_volume = _integer(chapter.volume_number)
    volume = (
        metadata_volume
        if metadata_volume is not None
        else int(match.group(1))
        if match
        else None
    )
    title = raw[: match.start()] + raw[match.end() :] if match else raw
    title = re.sub(r"\s*[-_:]+\s*$", "", title).strip()
    authors = chapter.authors
    if not match and not authors and " - " in title:
        possible_title, possible_author = title.rsplit(" - ", 1)
        if possible_title.strip() and possible_author.strip():
            title = possible_title.strip()
            authors = (possible_author.strip(),)
    return BookIdentity(
        title=title or chapter.title,
        volume=volume,
        authors=authors,
        pages=chapter.total_pages,
        isbn=chapter.isbn,
    )


def query_variants(
    identity: BookIdentity, aliases: tuple[str, ...] = ()
) -> tuple[str, ...]:
    """Build bounded provider queries, from most to least specific."""

    titles = (identity.title, *aliases)
    queries: list[str] = []
    for title in titles:
        title = " ".join(str(title).split())
        if not title:
            continue
        volume = f" {identity.volume}" if identity.volume is not None else ""
        author = f" {identity.authors[0]}" if identity.authors else ""
        queries.extend((f"{title}{volume}{author}", f"{title}{volume}", title))
    if identity.isbn:
        queries.insert(0, identity.isbn)
    return tuple(dict.fromkeys(query.strip() for query in queries if query.strip()))[:6]


def rank_candidates(
    identity: BookIdentity,
    editions: list[EditionCandidate],
    preferred_publishers: tuple[str, ...],
    preferred_sources: tuple[str, ...] = (),
) -> tuple[RankedCandidate, ...]:
    ranked = [
        RankedCandidate(
            edition=edition,
            score=_score(identity, edition, preferred_publishers, preferred_sources),
        )
        for edition in editions
    ]
    return tuple(
        sorted(ranked, key=lambda item: (-item.score, item.edition.target.media_id))
    )


def choose_match(
    ranked: tuple[RankedCandidate, ...],
    *,
    auto_score: int = 95,
    review_score: int = 80,
    min_margin: int = 8,
) -> MatchResult:
    if not ranked or ranked[0].score < review_score:
        return MatchResult(status="unmatched", candidates=ranked[:3])
    top = ranked[0]
    runner_up = ranked[1].score if len(ranked) > 1 else -1
    if top.score >= auto_score and top.score - runner_up >= min_margin:
        return MatchResult(status="auto", candidates=ranked[:3])
    return MatchResult(status="review", candidates=ranked[:3])


def _score(
    identity: BookIdentity,
    edition: EditionCandidate,
    preferred_publishers: tuple[str, ...],
    preferred_sources: tuple[str, ...],
) -> int:
    wanted_title = _normalize(identity.title)
    candidate_title, candidate_volume = _title_and_volume(edition.title)
    ratio = SequenceMatcher(None, wanted_title, candidate_title).ratio()
    score = 55 if wanted_title == candidate_title else round(45 * ratio)

    wanted_isbn = re.sub(r"[^0-9Xx]", "", identity.isbn or "").upper()
    candidate_isbns = {
        re.sub(r"[^0-9Xx]", "", value).upper() for value in edition.isbns if value
    }
    if wanted_isbn and wanted_isbn in candidate_isbns:
        score += 70

    if identity.volume is not None:
        if candidate_volume == identity.volume:
            score += 25
        elif candidate_volume is not None:
            score -= 45

    wanted_authors = {_normalize(author) for author in identity.authors}
    candidate_authors = {_normalize(author) for author in edition.authors}
    if wanted_authors and wanted_authors & candidate_authors:
        score += 10

    publisher_text = " ".join(_normalize(value) for value in edition.publishers)
    if any(
        _normalize(value) in publisher_text for value in preferred_publishers if value
    ):
        score += 12

    if any(
        _normalize(value) in {"spa", "es", "spanish", "espanol"}
        for value in edition.languages
    ):
        score += 8

    if edition.target.source in preferred_sources:
        score += max(1, 5 - preferred_sources.index(edition.target.source))

    if identity.pages > 0 and edition.pages > 0:
        difference = abs(identity.pages - edition.pages) / max(
            identity.pages, edition.pages
        )
        score += (
            10
            if difference <= 0.05
            else 6
            if difference <= 0.15
            else 2
            if difference <= 0.30
            else 0
        )
    return max(0, min(110, score))


def _title_and_volume(value: str) -> tuple[str, int | None]:
    match = _volume_match(value)
    volume = int(match.group(1)) if match else None
    title = value[: match.start()] if match else value
    return _normalize(title), volume


def _normalize(value: str) -> str:
    value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    )
    value = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return " ".join(value.split())


def _integer(value: str) -> int | None:
    return int(value) if str(value).strip().isdigit() else None


def _volume_match(value: str):
    explicit = _VOLUME.search(value)
    if explicit:
        return explicit
    trailing = _TRAILING_VOLUME.search(value)
    # Bare titles (1984), years and long numbers are not volume suffixes.
    return trailing if trailing and value[: trailing.start()].strip() else None
