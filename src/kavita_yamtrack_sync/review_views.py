"""Authenticated review panel for uncertain Open Library matches."""

from __future__ import annotations

import os
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_not_required, login_required
from django.http import (
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotFound,
    HttpResponseServerError,
    JsonResponse,
)
from django.shortcuts import redirect
from django.template import Engine, RequestContext
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from .config import load_config
from .http_clients import OpenLibraryClient, RemoteError
from .locking import LockTimeout
from .observability import account_status, healthy, status_path
from .review_store import (
    ReviewError,
    approve_candidate,
    approve_manual,
    get_reviews,
    ignore,
    reconsider,
)
from .state import load_state

CONFIG_ENV = "KAVITA_SYNC_CONFIG"
DEFAULT_CONFIG = "/run/kavita-yamtrack-sync/config.json"


@require_GET
@login_not_required
def health(request):
    return HttpResponse("ok", content_type="text/plain")


@require_GET
@login_not_required
def readiness(request):
    try:
        config = _config()
        ready = healthy(config, load_state(status_path(config)))
    except (OSError, ValueError, KeyError, TypeError):
        ready = False
    response = JsonResponse(
        {"status": "ok" if ready else "degraded"}, status=200 if ready else 503
    )
    response["Cache-Control"] = "no-store"
    return response


def csrf_failure(request, reason=""):
    return HttpResponseForbidden(
        "Request rejected: missing or invalid CSRF token.", content_type="text/plain"
    )


def bad_request(request, exception=None):
    return HttpResponseBadRequest("Invalid request.", content_type="text/plain")


def permission_denied(request, exception=None):
    return HttpResponseForbidden("Access denied.", content_type="text/plain")


def page_not_found(request, exception=None):
    return HttpResponseNotFound("Page not found.", content_type="text/plain")


def server_error(request):
    return HttpResponseServerError(
        "Internal review-panel error.", content_type="text/plain"
    )


@require_GET
@login_required(login_url="/accounts/login/")
def index(request):
    config = _config()
    snapshot = get_reviews(config, request.user.get_username())
    chapters = []
    for chapter_id, record in sorted(
        snapshot.chapters.items(), key=lambda item: int(item[0])
    ):
        chapters.append(
            {
                "chapter_id": chapter_id,
                "status": record.get("status", "review"),
                "status_label": {
                    "review": "Under review",
                    "unmatched": "No match",
                    "ignored": "Ignored",
                    "identity_changed": "Metadata changed",
                }.get(record.get("status", "review"), "Under review"),
                "signature": record.get("signature", {}),
                "candidates": record.get("candidates", []),
            }
        )
    return _page(request, chapters, account_status(config, request.user.get_username()))


@require_POST
@csrf_protect
@login_required(login_url="/accounts/login/")
def approve(request, chapter_id):
    candidate = request.POST.get("candidate", "")
    source, separator, media_id = candidate.partition("|")
    if not separator:
        source, media_id = None, candidate
    return _mutation(
        request,
        lambda: approve_candidate(
            _config(),
            request.user.get_username(),
            chapter_id,
            media_id,
            source,
        ),
        "Candidate approved. Yamtrack will be updated during the next sync.",
    )


@require_POST
@csrf_protect
@login_required(login_url="/accounts/login/")
def manual(request, chapter_id):
    media_id = request.POST.get("media_id", "").strip().upper()

    def action():
        # Validate against the fixed Open Library origin before persisting a
        # manually typed ID. No user-controlled URL is ever requested.
        edition = OpenLibraryClient().get_edition(media_id)
        if edition is None:
            raise ReviewError("That edition does not exist in Open Library")
        approve_manual(_config(), request.user.get_username(), chapter_id, media_id)

    return _mutation(
        request,
        action,
        "Manual edition approved. Yamtrack will be updated during the next sync.",
    )


@require_POST
@csrf_protect
@login_required(login_url="/accounts/login/")
def ignore_item(request, chapter_id):
    return _mutation(
        request,
        lambda: ignore(_config(), request.user.get_username(), chapter_id),
        "Item ignored. It will not be synchronized until its metadata changes.",
    )


@require_POST
@csrf_protect
@login_required(login_url="/accounts/login/")
def reconsider_item(request, chapter_id):
    return _mutation(
        request,
        lambda: reconsider(_config(), request.user.get_username(), chapter_id),
        "Candidates will be searched again during the next sync.",
    )


def _mutation(request, action, success):
    try:
        action()
    except (ReviewError, LockTimeout, OSError, ValueError, RemoteError) as error:
        messages.error(request, str(error))
    else:
        messages.success(request, success)
    return redirect("kavita_sync_review")


def _config():
    return load_config(os.environ.get(CONFIG_ENV, DEFAULT_CONFIG))


def _page(request, chapters, sync_status):
    template_path = Path(__file__).with_name("review.html")
    template = Engine.get_default().from_string(
        template_path.read_text(encoding="utf-8")
    )
    context = RequestContext(
        request,
        {
            "sync": sync_status,
            "chapters": chapters,
            "pending_count": sum(item["status"] != "ignored" for item in chapters),
            "ignored_count": sum(item["status"] == "ignored" for item in chapters),
        },
    )
    response = HttpResponse(template.render(context))
    response["Cache-Control"] = "no-store"
    return response
