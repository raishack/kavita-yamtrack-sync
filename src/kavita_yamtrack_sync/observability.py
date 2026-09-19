"""Credential-free sync health, independent of the review web process."""

import logging
import time
from datetime import datetime, timezone

from .state import load_state


def status_path(config):
    return config.state_file.with_name("status.json")


def error_code(error):
    if type(error).__name__ in {"SyncConflict", "CommandError"}:
        return (
            str(error)
            if str(error)
            in {
                "identity_changed_review_required",
                "existing_reading_migration_conflict",
                "reading_deleted_or_replaced",
                "unknown_previous_page_scale",
                "orm_changed_requested_progress",
                "incompatible_yamtrack_version",
                "incompatible_kavita_version",
                "partial_failure_see_status",
            }
            else "sync_failed"
        )
    status = getattr(error, "status", None)
    return f"remote_http_{status}" if isinstance(status, int) else type(error).__name__


ERROR_LABELS = {
    "identity_changed_review_required": "Han cambiado los metadatos. Revisa la edición antes de continuar.",
    "existing_reading_migration_conflict": "Ya existe otra lectura de esa edición. Ambas fichas se han conservado; hay que revisar la migración.",
    "reading_deleted_or_replaced": "La ficha vinculada fue borrada o sustituida. No se ha recreado ni alterado la nueva lectura.",
    "unknown_previous_page_scale": "Faltan las páginas de la edición anterior; no se ha convertido el progreso.",
    "orm_changed_requested_progress": "Yamtrack ha cambiado el progreso solicitado. La escritura se ha revertido.",
}


def healthy(config, health, *, now=None):
    now = time.time() if now is None else now
    return bool(
        health.get("status") in {"ok", "running"}
        and health.get("last_success_at")
        and 0 <= now - health["last_success_at"] <= config.stale_after_seconds
        and (
            health.get("status") != "running"
            or now - health.get("started_at", 0) <= config.stale_after_seconds
        )
    )


def account_status(config, username):
    configured = any(a.yamtrack_username == username for a in config.accounts)
    if not configured:
        return {"configured": False}
    health = load_state(status_path(config))
    record = health.get("accounts", {}).get(username, {})
    errors = []
    for error in record.get("errors", [])[:100]:
        errors.append(
            {
                "chapter_id": error.get("chapter_id"),
                "message": ERROR_LABELS.get(
                    error.get("code"),
                    "No se pudo consultar o sincronizar este elemento. Se reintentará automáticamente.",
                ),
            }
        )
    last = record.get("last_success_at")
    return {
        "configured": True,
        "healthy": healthy(config, record) and health.get("status") != "failed",
        "status": record.get("status", "unknown"),
        "last_success": datetime.fromtimestamp(last, tz=timezone.utc) if last else None,
        "duration": health.get("duration_seconds"),
        "manual": record.get("manual", 0),
        "errors": errors,
        "global_failed": health.get("status") == "failed",
    }


class ProviderLogFilter(logging.Filter):
    """Upstream ProviderAPIError logs response bodies; omit them in this job."""

    def filter(self, record):
        if record.levelno >= logging.WARNING:
            record.msg = "Provider request failed; see sanitized sync status"
            record.args = ()
            record.exc_info = None
            record.exc_text = None
        return True
