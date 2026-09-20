# Development and testing

## Architecture

- `core.py`: progress, date, and proportion decisions.
- `http_clients.py`: Kavita/Open Library clients, header authentication, timeouts, and retries.
- `matching.py`: bibliographic identity, ranking, and conservative selection.
- `automation.py`: fallback and reconciliation.
- `state.py`, `locking.py`: atomic file persistence and mutual exclusion.
- `observability.py`: summarized health and errors.
- `review_*`, `review.html`: Django panel using Yamtrack sessions with per-user isolation.
- `deploy/django_management/commands/sync_kavita.py`: orchestration, real models/providers, and transactions.

## Unit tests (no services or secrets)

From the repository root, with Python 3.12+:

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
python -m pip install ruff==0.15.6
python -m ruff check .
```

A virtual environment is recommended. Unit tests do not import Django. The real management command must run inside the validated Yamtrack image, not an arbitrary Django installation.

## Integration with real Yamtrack models

First pull the pinned image described in [Installation](INSTALL.md), then run:

```sh
./deploy/test-image.sh ghcr.io/fuzzygrim/yamtrack@sha256:78497b454b2b52d3b1062f6fd238351d714cff0895db4369e49ace36f4622e75
```

The script resolves and pins the image ID, runs the unit suite, and then starts Django with an in-memory SQLite database, Yamtrack's original migrations, and simulated providers. It uses `--network none` and mounts neither secrets nor production state. It verifies `Book.save`, history, transactions, collisions, CSRF, isolation, dry-run behavior, and resumption.

CI runs both suites on every push and pull request with read-only permissions. It does not deploy or publish automatically. Simulated HTTP tests are not a substitute for live integration against every Kavita version.

## Contributing

Keep changes small and add tests for decisions that affect readings. Never commit databases or credentials. Preserve strict version guards and dry-run defaults. Do not change deterministic identities or the state schema without a migration plan. Before publishing, inspect the complete tree and artifacts and run a secret scanner. A public checkout is not the active production deployment.
