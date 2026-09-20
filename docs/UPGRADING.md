# Controlled upgrades and rollback

The connector depends on Kavita APIs and Yamtrack's internal models. Never upgrade from `latest`, remove version guards, or copy patched binaries from one version into another.

## Procedure

1. Inventory versions, image digests, mounts, configuration, timer, and local extensions. Preserve original files and unrelated local changes.
2. Download the official candidate and verify its identity/hash. For Yamtrack, run `deploy/test-image.sh` against an immutable image ID/digest.
3. Obtain a consistent copy of the database (SQLite backup API or all writers stopped), JSON state, configuration, protected keys, images, and connector code. Verify integrity and restorability. Restrict access; never attach backups to the repository.
4. Start an isolated instance using the copy, with scheduled jobs disabled and no output to real integrations. Do not mount original book storage as writable or point the test instance at production Yamtrack.
5. Verify migration and integrity; compare progress, dates, notes, ratings, primary keys, and history. Test authentication and account isolation.
6. Kavita: test header authentication, paginated history, on-deck, details, and manga/EPUB progress. Run the complete connector in dry-run mode against the test instance.
7. Yamtrack: test ORM integration, simulated providers, panel, CSRF, isolation, transactions, and idempotency. Synthetic tests do not replace migrating a real backup.
8. Only after all checks pass: pause the timer, wait for the active job, stop writers, and create a fresh final backup. Update code/image/configuration without replacing live secrets or JSON state. Yamtrack and panel services must use the same digest.
9. Add only the exact newly validated version to configuration. Recreate services when replacing bind-mounted files so the new inode is mounted.
10. Run a dry-run, review decisions, run one real cycle and a second idempotency cycle. Check HTTPS, readiness, login, notes, and readings. Restore the timer's previous state and monitor its first automatic run.
11. Record version, digest/hash, backup, tests, incidents, and rollback recipe in private documentation. A working web page alone is not proof of a successful upgrade.

## Validated reference

On 2026-09-19, Kavita **0.9.0.2 → 0.9.1.4** was validated with Yamtrack **0.26.3**: isolated-copy migration, database integrity, progress/history queries, and dry-run, followed by a production cycle with no errors. Only the allowlist changed; the synchronization algorithm did not.

The **Troop Reader** integration was validated separately. Kavita 0.9.1.4 still required an image-parameter compatibility adjustment for that app; **this connector does not need that patch**. See the [Troop Reader repository](https://github.com/raishack/troop-reader) if you use both.

## Rollback

Stop the timer, wait for the active job, and stop the panel. Preserve a copy of the new state first. Restore compatible code, configuration, and the previous image, then recreate only affected services. Do not roll back an entire database to revert connector code; doing so would lose newer readings.

If a migration requires restoring the database, stop **all** writers and restore the consistent database/JSON/code/configuration set. Document which later changes will be lost. Never start old binaries against a migrated database while assuming downgrade compatibility. Verify integrity, dry-run output, idempotency, and health before re-enabling the timer.
