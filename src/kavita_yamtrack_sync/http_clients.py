"""Minimal clients for Kavita and Open Library."""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .core import (
    KavitaChapter,
    YamtrackTarget,
    chapter_ids_from_history,
    history_bounds,
    normalize_isbn,
)
from .matching import (
    EditionCandidate,
    MatchResult,
    choose_match,
    infer_identity,
    query_variants,
    rank_candidates,
)


class RemoteError(RuntimeError):
    """A sanitized remote-service failure that never includes credentials."""

    def __init__(self, message, *, status=None):
        super().__init__(message)
        self.status = status

    @property
    def fatal(self):
        return self.status in {401, 403}


class _RejectRedirects(HTTPRedirectHandler):
    """Do not forward API-key bearing URLs to a redirected origin."""

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


class _CatalogRedirects(HTTPRedirectHandler):
    max_repeats = 2
    max_redirections = 3

    def redirect_request(self, request, fp, code, msg, headers, new_url):
        parsed = urlsplit(new_url)
        if (
            (parsed.scheme, parsed.hostname, parsed.port)
            != ("https", "openlibrary.org", None)
            or parsed.username
            or parsed.password
        ):
            return None
        if request.get_method() != "GET":
            return None
        return super().redirect_request(request, fp, code, msg, headers, new_url)


class JsonClient:
    def __init__(self, timeout: int = 20, *, public_catalog=False):
        self.timeout = timeout
        self.opener = build_opener(
            _CatalogRedirects() if public_catalog else _RejectRedirects()
        )

    def request(self, method: str, url: str, *, headers=None):
        request = Request(url, method=method, headers=headers or {})
        for attempt in range(3):
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    body = json.loads(response.read().decode("utf-8"))
                    return body, dict(response.headers.items())
            except HTTPError as error:
                status = error.code
                error.close()
                if (
                    method == "GET"
                    and status in {429, 500, 502, 503, 504}
                    and attempt < 2
                ):
                    time.sleep(2**attempt)
                    continue
                raise RemoteError(
                    f"Remote service returned HTTP {status}", status=status
                ) from None
            except (URLError, TimeoutError, OSError) as error:
                if method == "GET" and attempt < 2:
                    time.sleep(2**attempt)
                    continue
                raise RemoteError(
                    f"Remote service request failed: {type(error).__name__}"
                ) from None
            except (UnicodeError, json.JSONDecodeError):
                raise RemoteError("Remote service returned invalid JSON") from None


class KavitaClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 20):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.http = JsonClient(timeout)
        self.token: str | None = None
        self.server_version: str | None = None
        self.errors = []

    def authenticate(self) -> None:
        # The authenticated account endpoint returns the same token/version
        # contract without putting the auth key in URLs or access logs.
        body, _ = self.http.request(
            "GET", f"{self.base_url}/api/Account/refresh-account",
            headers={"x-api-key": self.api_key, "Accept": "application/json"},
        )
        token = body.get("token") if isinstance(body, dict) else None
        if not token:
            raise RemoteError("Kavita authentication returned no token")
        self.token = token
        version = body.get("kavitaVersion")
        self.server_version = str(version).strip().lstrip("v") if version else None

    def get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> tuple[Any, dict[str, str]]:
        if not self.token:
            raise RuntimeError("Kavita client is not authenticated")
        query = f"?{urlencode(params, doseq=True)}" if params else ""
        return self.http.request(
            "GET",
            f"{self.base_url}/api/{path.lstrip('/')}{query}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
            },
        )

    def reading_history(self, page_size: int = 100) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        for page in range(1, 1001):
            body, _ = self.get(
                "Stats/reading-history",
                {"pageNumber": page, "pageSize": page_size},
            )
            if not isinstance(body, list):
                raise RemoteError(
                    "Kavita reading history returned an unexpected payload"
                )
            history.extend(body)
            if len(body) < page_size:
                return history
        raise RemoteError("Kavita reading history exceeded the pagination safety limit")

    def chapters_with_progress(
        self, *, cache=None, cache_seconds=0
    ) -> list[KavitaChapter]:
        self.errors = []
        cache = cache if cache is not None else {}
        history = self.reading_history()
        chapters: dict[int, KavitaChapter] = {}
        for chapter_id in sorted(chapter_ids_from_history(history)):
            try:
                bounds = history_bounds(history, chapter_id)
                fingerprint = hashlib.sha256(repr(bounds).encode()).hexdigest()
                entry = cache.get(str(chapter_id), {})
                if (
                    entry.get("fingerprint") == fingerprint
                    and time.time() - entry.get("fetched_at", 0) < cache_seconds
                ):
                    body = entry["body"]
                else:
                    body, _ = self.get("Chapter", {"chapterId": chapter_id})
                    if isinstance(body, dict):
                        cache[str(chapter_id)] = {
                            "body": body,
                            "fingerprint": fingerprint,
                            "fetched_at": int(time.time()),
                        }
                if not isinstance(body, dict):
                    raise RemoteError("Kavita chapter returned an unexpected payload")
                first, last, completed = history_bounds(history, chapter_id)
                chapters[chapter_id] = _chapter(
                    body,
                    series_id=int(
                        body.get("seriesId") or _series_id(history, chapter_id)
                    ),
                    series_name=_series_name(history, chapter_id),
                    authors=_writers(body),
                    first_read_at=first,
                    last_read_at=last,
                    completed=completed,
                )
            except RemoteError as error:
                if error.fatal:
                    raise
                self.errors.append(
                    {
                        "chapter_id": chapter_id,
                        "code": f"chapter_http_{error.status or 'failed'}",
                    }
                )
            except (ValueError, TypeError, KeyError):
                self.errors.append(
                    {"chapter_id": chapter_id, "code": "chapter_payload"}
                )

        # Reading-history rows are aggregated asynchronously by Kavita. Pull
        # current on-deck progress as well so a fresh read can sync immediately.
        try:
            on_deck = self.on_deck_series()
        except RemoteError as error:
            if error.fatal:
                raise
            self.errors.append({"code": f"on_deck_http_{error.status or 'failed'}"})
            on_deck = []
        for series in on_deck:
            series_id = int(series.get("id") or 0)
            if series_id <= 0:
                continue
            try:
                metadata, _ = self.get("Series/metadata", {"seriesId": series_id})
                volumes, _ = self.get("Series/volumes", {"seriesId": series_id})
                if not isinstance(metadata, dict) or not isinstance(volumes, list):
                    raise RemoteError(
                        "Kavita series progress returned an unexpected payload"
                    )
                authors = _writers(metadata)
                for volume in volumes:
                    for body in volume.get("chapters") or []:
                        chapter_id = int(body.get("id") or 0)
                        pages_read = max(0, int(body.get("pagesRead") or 0))
                        total_reads = max(0, int(body.get("totalReads") or 0))
                        if chapter_id <= 0 or (pages_read <= 0 and total_reads <= 0):
                            continue
                        existing = chapters.get(chapter_id)
                        chapters[chapter_id] = _chapter(
                            body,
                            series_id=series_id,
                            series_name=str(series.get("name") or "").strip(),
                            authors=authors,
                            first_read_at=existing.first_read_at if existing else None,
                            last_read_at=existing.last_read_at if existing else None,
                            completed=existing.completed if existing else False,
                        )
            except RemoteError as error:
                if error.fatal:
                    raise
                self.errors.append(
                    {
                        "series_id": series_id,
                        "code": f"series_http_{error.status or 'failed'}",
                    }
                )
            except (ValueError, TypeError, KeyError):
                self.errors.append({"series_id": series_id, "code": "series_payload"})
        return [chapters[key] for key in sorted(chapters)]

    def on_deck_series(self, page_size: int = 100) -> list[dict[str, Any]]:
        series: list[dict[str, Any]] = []
        for page in range(1, 1001):
            params = urlencode(
                {"PageNumber": page, "PageSize": page_size, "libraryId": 0}
            )
            body, _ = self.http.request(
                "POST",
                f"{self.base_url}/api/Series/on-deck?{params}",
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Accept": "application/json",
                },
            )
            if not isinstance(body, list):
                raise RemoteError("Kavita on-deck returned an unexpected payload")
            series.extend(body)
            if len(body) < page_size:
                return series
        raise RemoteError("Kavita on-deck exceeded the pagination safety limit")


class OpenLibraryClient:
    def __init__(self, timeout: int = 20):
        self.http = JsonClient(timeout, public_catalog=True)

    def resolve_isbn(self, isbn: str) -> YamtrackTarget | None:
        isbn = normalize_isbn(isbn)
        if not isbn:
            return None
        try:
            body, _ = self.http.request(
                "GET",
                f"https://openlibrary.org/isbn/{isbn}.json",
                headers={"User-Agent": "Kavita-Yamtrack-Sync/0.1"},
            )
        except RemoteError as error:
            if error.status == 404:
                return None
            raise
        key = body.get("key") if isinstance(body, dict) else None
        if not isinstance(key, str) or not re.fullmatch(r"/books/OL\d+M", key):
            return None
        return YamtrackTarget(
            source="openlibrary", media_id=key.rstrip("/").split("/")[-1]
        )

    def get_edition(self, media_id: str) -> dict[str, Any] | None:
        if not re.fullmatch(r"OL\d+M", media_id):
            return None
        try:
            body, _ = self.http.request(
                "GET",
                f"https://openlibrary.org/books/{media_id}.json",
                headers={"User-Agent": "Kavita-Yamtrack-Sync/0.3"},
            )
        except RemoteError as error:
            if error.status == 404:
                return None
            raise
        if not isinstance(body, dict) or body.get("key") != f"/books/{media_id}":
            return None
        return body

    def suggest(
        self,
        chapter: KavitaChapter,
        *,
        preferred_publishers: tuple[str, ...] = ("Norma",),
        preferred_sources: tuple[str, ...] = (),
        title_aliases: tuple[str, ...] = (),
        auto_score: int = 95,
        review_score: int = 80,
        min_margin: int = 8,
    ) -> MatchResult:
        identity = infer_identity(chapter)
        fields = ",".join(("key", "title", "author_name", "edition_key"))
        editions: dict[str, EditionCandidate] = {}
        seen_works: set[str] = set()
        for query in query_variants(identity, title_aliases):
            if len(seen_works) >= 8:
                break
            try:
                body, _ = self.http.request(
                    "GET",
                    "https://openlibrary.org/search.json?"
                    + urlencode({"q": query, "fields": fields, "limit": 8}),
                    headers={"User-Agent": "Kavita-Yamtrack-Sync/0.4"},
                )
            except RemoteError as error:
                if error.status == 404:
                    continue
                raise
            for edition in self._editions(body, seen_works, max_works=8):
                editions[edition.target.media_id] = edition
        ranked = rank_candidates(
            identity,
            list(editions.values()),
            preferred_publishers,
            preferred_sources,
        )
        return choose_match(
            ranked,
            auto_score=auto_score,
            review_score=review_score,
            min_margin=min_margin,
        )

    def _editions(
        self,
        search_body: Any,
        seen_works: set[str] | None = None,
        *,
        max_works: int = 8,
    ) -> list[EditionCandidate]:
        candidates: dict[str, EditionCandidate] = {}
        seen_works = seen_works if seen_works is not None else set()
        documents = search_body.get("docs", []) if isinstance(search_body, dict) else []
        for document in documents:
            if len(seen_works) >= max_works:
                break
            work_key = str(document.get("key") or "")
            if not work_key.startswith("/works/") or work_key in seen_works:
                continue
            seen_works.add(work_key)
            try:
                body, _ = self.http.request(
                    "GET",
                    f"https://openlibrary.org{work_key}/editions.json?limit=50",
                    headers={"User-Agent": "Kavita-Yamtrack-Sync/0.4"},
                )
            except RemoteError as error:
                if error.status == 404:
                    continue
                raise
            for entry in body.get("entries", []) if isinstance(body, dict) else []:
                key = str(entry.get("key") or "")
                if not key.startswith("/books/"):
                    continue
                media_id = key.rstrip("/").split("/")[-1]
                languages = tuple(
                    str(value.get("key") or "").rsplit("/", 1)[-1]
                    for value in entry.get("languages", [])
                    if isinstance(value, dict)
                )
                candidates[media_id] = EditionCandidate(
                    target=YamtrackTarget(source="openlibrary", media_id=media_id),
                    title=str(entry.get("title") or document.get("title") or ""),
                    authors=tuple(
                        str(value) for value in document.get("author_name", []) if value
                    ),
                    publishers=tuple(
                        str(value) for value in entry.get("publishers", []) if value
                    ),
                    languages=languages,
                    pages=max(0, int(entry.get("number_of_pages") or 0)),
                    isbns=tuple(
                        str(value)
                        for key in ("isbn_10", "isbn_13")
                        for value in (entry.get(key) or [])
                        if value
                    ),
                    image=(
                        f"https://covers.openlibrary.org/b/id/{entry['covers'][0]}-L.jpg"
                        if entry.get("covers")
                        else ""
                    ),
                )
        return list(candidates.values())


def _series_id(history: list[dict[str, Any]], chapter_id: int) -> int:
    for session in history:
        if any(
            chapter.get("chapterId") == chapter_id
            for chapter in session.get("chapters") or []
        ):
            return int(session.get("seriesId") or 0)
    return 0


def _series_name(history: list[dict[str, Any]], chapter_id: int) -> str:
    for session in history:
        if any(
            chapter.get("chapterId") == chapter_id
            for chapter in session.get("chapters") or []
        ):
            return str(session.get("seriesName") or "")
    return ""


def _writers(body: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(writer.get("name", "")).strip()
        for writer in (body.get("writers") or [])
        if str(writer.get("name", "")).strip()
    )


def _chapter(
    body: dict[str, Any],
    *,
    series_id: int,
    series_name: str,
    authors: tuple[str, ...],
    first_read_at,
    last_read_at,
    completed: bool,
) -> KavitaChapter:
    files = body.get("files") or []
    file_path = (
        str(files[0].get("filePath") or "")
        if files and isinstance(files[0], dict)
        else ""
    )
    file_name = file_path.replace("\\", "/").rsplit("/", 1)[-1]
    return KavitaChapter(
        chapter_id=int(body.get("id") or body.get("chapterId") or 0),
        series_id=series_id,
        title=str(
            body.get("titleName") or series_name or body.get("title") or ""
        ).strip(),
        authors=authors,
        isbn=normalize_isbn(body.get("isbn") or body.get("ISBN")),
        pages_read=max(0, int(body.get("pagesRead") or 0)),
        total_pages=max(0, int(body.get("pages") or 0)),
        total_reads=max(0, int(body.get("totalReads") or 0)),
        completed=completed,
        first_read_at=first_read_at,
        last_read_at=last_read_at,
        file_name=file_name,
        volume_number=str(body.get("number") or "").strip(),
    )
