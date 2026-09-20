# Configuration

Start from [config.example.json](../deploy/config.example.json). The schema version is 1. The example contains no real values or user overrides.

| Field | Recommended value / meaning |
|---|---|
| `kavita_url` | HTTPS URL without credentials; HTTP is accepted only for an explicit, non-loopback private IP on a controlled network |
| `state_file` | Persistent private JSON shared by the command and review panel |
| `review_file` | Private queue; defaults to `review.json` next to the state file |
| `accounts` | Exact Yamtrack username → API-key file for the same Kavita reader |
| `accounts[].overrides` | Kavita chapter ID → `{ "source": "openlibrary", "media_id": "OL123456M" }`; fictional example—never copy IDs blindly |
| `allowed_kavita_versions` | Exact validated allowlist; example: 0.9.0.2 and 0.9.1.4 |
| `allowed_yamtrack_versions` | Exact validated allowlist; example: 0.26.1 and 0.26.3 |
| `timeout_seconds` | 20; constrained to 5–120 |
| `allow_regress` | false; do not enable it to repair an incorrect match |
| `auto_match_min_score` | 95 |
| `review_match_min_score` | 80 |
| `auto_match_min_margin` | 8 points above the second candidate |
| `preferred_publishers` | Example: `Norma`; customize for your library or use `[]` |
| `hardcover_enabled` | true; requires the provider to be configured in Yamtrack |
| `manual_fallback_after_cycles` | 3; persistent ambiguity creates a deterministic manual entry |
| `manual_reconcile_hours` | 24; retries canonical-edition matching for manual entries |
| `metadata_cache_seconds` | 3600; 0 disables detail caching |
| `stale_after_seconds` | 3600; readiness fails when no recent successful run exists |

## Identity and matching

ISBNs, explicit overrides, and user decisions drive matching. Title, author, volume, publisher, language, and page count help distinguish editions. A different volume must not be accepted merely because it belongs to the same series. Kavita `chapterId` values are internal reading-unit identifiers: they may represent books, parts, or volumes—not only literary chapters.

If two readings resolve to the same edition, the connector reports a conflict and preserves both. A deleted or replaced reading is not silently recreated. Do not delete `state.json` to fix a matching problem; doing so discards identity, decisions, and synchronization history.

Progress is converted proportionally to the Yamtrack edition's page count. An incomplete reading is never rounded up to completion. A completed entry is not reopened automatically.

## Review panel

Each user sees only their own queue. Approving a candidate or selecting another edition stores a decision that is applied by the next synchronization run. Ignore remains effective until identity metadata changes; search again invalidates the current search decision. Writes use POST + CSRF and share the command lock.

Provider secrets, when required, use Yamtrack's own configuration mechanisms. There is no global Kavita API key that replaces individual reader keys.
