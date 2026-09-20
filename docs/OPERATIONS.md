# Operations and troubleshooting

## Persistent state

- `state.json`: identities, entry links, decisions, cache, and retries.
- `review.json`: proposals awaiting manual review.
- `status.json`: latest global/per-account result, duration, and error codes.
- `sync.lock`: shared lock between the command and review panel.

These are private files, normally mode 0600. Do not edit them while the timer or panel is active. ORM and JSON writes are not one distributed transaction: each book is committed and then a checkpoint is persisted. Deterministic identities make interrupted runs resumable.

## Health

`/kavita-sync/health/` is a liveness endpoint. `/kavita-sync/ready/` returns 200 only after a recent successful run, or 503 when degraded. Do not use readiness as a restart-loop policy; fix the underlying cause. A partial failure exits nonzero even when other books were updated successfully.

## Common problems

| Symptom | What to check |
|---|---|
| `incompatible_kavita_version` / `incompatible_yamtrack_version` | Intentional guard. Validate the exact version before extending the allowlist |
| API-key read error | File, **container path**, owner, and mode 0600; never print its contents |
| HTTP 401/403 | Per-user key, library permissions, correct URL, and support for header authentication |
| Missing `sync_kavita` command | `/yamtrack/app/management` mount and package at `/yamtrack/kavita_yamtrack_sync` |
| Panel redirects back to login | Same origin, session secret, user database, and effective panel configuration |
| Panel rejects POST | CSRF, cookies, and HTTPS proxy headers; never disable protection |
| Entry takes time to appear | Only reading units with progress are imported; delayed history + on-deck; inspect queue and counters |
| Provider unavailable | Provider errors do not mean “no match”; retries use increasing delays |
| API returns HTML/redirect | Use the canonical base URL; authenticated redirects are not followed |
| New config not applied | A bind-mounted file may keep the old inode; recreate affected services |
| Progress appears lower between editions | Compare proportional page counts before treating it as a regression |

To query pending proposals again:

```sh
docker exec yamtrack python manage.py sync_kavita --config /run/kavita-yamtrack-sync/config.json --refresh-matches
```

Without `--apply`, the search is not persisted. Add the flag only when you intend to store and apply decisions. Never publish logs without reviewing them: although the connector summarizes errors, dependencies or external tools may include sensitive data.
