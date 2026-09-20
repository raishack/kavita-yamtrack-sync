# Installation

## 1. Requirements and backup

You need a working Yamtrack installation, Docker Compose, host access, and a validated Kavita version. This extension uses internal paths and APIs from the Yamtrack image (`/yamtrack`, `app.management`, and `Book.save`), so changing the image requires testing.

Before changing mounts, stop writers or use SQLite's backup API to create a consistent copy. Also preserve Compose files, configuration, the exact image reference, and connector state if it already exists. Never copy a live SQLite database without handling its WAL.

Examples assume a stack at `/opt/yamtrack`, a `yamtrack` container, a Redis service named `redis`, a `./db` volume, and a `caddy_default` proxy network. **Adapt these names to your stack**; do not replace your entire existing Compose file.

## 2. Code and image

From the stack directory:

```sh
git clone https://github.com/raishack/kavita-yamtrack-sync.git
cd kavita-yamtrack-sync
git checkout v0.2.1
cp deploy/config.example.json config.json
install -d -m 700 secrets
cd ..
install -d -m 700 db/kavita-yamtrack-sync
```

Set `YAMTRACK_VALIDATED_IMAGE` in your private Compose configuration to the tested **digest**, never `latest`. This image identifier is not a secret. Reference image for Yamtrack 0.26.3:

```text
ghcr.io/fuzzygrim/yamtrack@sha256:78497b454b2b52d3b1062f6fd238351d714cff0895db4369e49ace36f4622e75
```

Pull and test it before deployment:

```sh
docker pull ghcr.io/fuzzygrim/yamtrack@sha256:78497b454b2b52d3b1062f6fd238351d714cff0895db4369e49ace36f4622e75
./kavita-yamtrack-sync/deploy/test-image.sh ghcr.io/fuzzygrim/yamtrack@sha256:78497b454b2b52d3b1062f6fd238351d714cff0895db4369e49ace36f4622e75
```

Tests use disposable containers, no network, and an in-memory database—never your volumes. If the digest does not support your architecture, validate an official image for that architecture before proceeding.

## 3. Configuration and API keys

In Kavita, each reader creates their own API key from user preferences. Use your host's secret manager or secure editor to create `kavita-yamtrack-sync/secrets/kavita-reader-api-key`. **Never paste the key into commands, URLs, Git, issues, or logs.** The file must contain only the key, be readable by the user running the command in the container, and use mode `0600` (or stricter). The connector rejects group/other permissions.

```sh
chmod 600 kavita-yamtrack-sync/secrets/kavita-reader-api-key
chmod 600 kavita-yamtrack-sync/config.json
```

Edit the JSON with your Kavita HTTPS URL, the **exact** Yamtrack username, the in-container path to the key file, and explicit allowed versions. Do not put the key itself in JSON. Add separate mappings and mounts for more users. See [Configuration](CONFIGURATION.md).

## 4. Mounts and optional review panel

Merge the [example override](../deploy/docker-compose.override.example.yml) into your Compose project. Command mounts are required. The `yamtrack-kavita-review` service and Caddy network are optional if you do not need the review panel.

- The `/yamtrack/app/management` mount replaces that directory inside the container. Review and merge any existing custom commands before using it.
- The command and panel must use the **same Yamtrack digest**, database, configuration, and state directory.
- The example loads `.env` into the panel. It must provide the same settings Yamtrack receives (session `SECRET`, URLs/origins, database, Redis, and providers). Adapt the service if your stack uses different names or file-based secrets. Do not change the session secret to install the panel.
- Do not mount Kavita API keys into the panel; only the command needs them. Mount each key separately.
- Preserve Yamtrack cookies, CSRF origins, proxy headers, and authentication. Never disable CSRF to work around a 403.
- Verify volume ownership and UID. The command and panel both need write access to state and lock files. Never solve this with mode `777`.

Validate Compose syntax **without dumping secret values**, then recreate only modified services:

```sh
docker compose config --quiet
docker compose up -d yamtrack yamtrack-kavita-review
```

If you omit the panel, recreate only `yamtrack`.

For Caddy, add the [provided snippet](../deploy/Caddyfile.review.snippet) to the same HTTPS site as Yamtrack, before the general reverse proxy. The network must allow Caddy to resolve `yamtrack-kavita-review`. Do not add `ports:` to the panel. Keep the trailing slash in `/kavita-sync/`. You may add a visible link from your landing page; the extension does not modify Yamtrack's original navigation.

## 5. Dry-run and first apply

```sh
docker exec yamtrack python manage.py sync_kavita --config /run/kavita-yamtrack-sync/config.json
```

Output summarizes decisions; it is not a table of every reading. Review metadata and overrides, and validate against an isolated copy when you need to inspect every association. A run with no errors does not prove ambiguous titles were identified correctly—review the `review`, `unmatched`, and `manual_fallback` counters.

After backup and review:

```sh
docker exec yamtrack python manage.py sync_kavita --config /run/kavita-yamtrack-sync/config.json --apply
```

Run it again to verify idempotency. With no new reading changes, it must not duplicate entries or history. Operational timestamps may still update. Check notes, ratings, progress, and dates before enabling automation.

## 6. Automation

Adapt paths, Docker executable, and container names in `deploy/systemd/`. The service **includes `--apply`**; do not enable it before completing the pilot.

```sh
sudo install -m 644 kavita-yamtrack-sync/deploy/systemd/yamtrack-kavita-sync.service /etc/systemd/system/
sudo install -m 644 kavita-yamtrack-sync/deploy/systemd/yamtrack-kavita-sync.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now yamtrack-kavita-sync.timer
```

It runs five minutes after the previous cycle finishes, with up to 30 seconds of jitter. The shared lock prevents overlap. Do not enable another cron job for the same configuration. On a NAS without systemd, use its scheduler while serializing the same command.

## 7. Verification

```sh
sudo systemctl status yamtrack-kavita-sync.timer --no-pager
sudo journalctl -u yamtrack-kavita-sync.service -n 30 --no-pager
docker port yamtrack-kavita-review
curl --fail https://yamtrack.example.org/kavita-sync/health/
curl --fail https://yamtrack.example.org/kavita-sync/ready/
```

The review panel must expose no published ports. Verify anonymous users are redirected to login and that two accounts cannot access one another's queues. `ready` may return 503 until the first successful apply run; `health` only confirms that the process responds.
