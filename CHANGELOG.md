# Changelog

## 0.2.1 — first standalone release

- Public installation, operations, testing, upgrade, and rollback documentation.
- Example configuration validated with Kavita 0.9.0.2 and 0.9.1.4, and Yamtrack 0.26.1 and 0.26.3.
- CI using an immutable Yamtrack image digest and a disposable offline database.
- Package now includes the review-panel template; package metadata and internal version are consistent.
- Private reports, deployment configuration, and production data removed from the public copy.
- No synchronization-algorithm changes from 0.2.0. This release does not automatically upgrade existing installations.

## 0.2.0 — functional baseline

- Manual reconciliation and proportional conversion without premature completion.
- Preserves primary keys, notes, ratings, and history when migrating an entry.
- Isolated failures per account/book, retries, and checkpoints.
- Per-account health, readiness, caching, and deployment with a validated image.
