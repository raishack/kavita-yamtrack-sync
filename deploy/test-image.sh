#!/bin/sh
# Run against an immutable, already available Yamtrack image, never live data.
set -eu
[ "$#" -eq 1 ] || { echo 'Usage: test-image.sh IMAGE_ID_OR_DIGEST' >&2; exit 2; }
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
image_id=$(docker image inspect --format '{{.Id}}' "$1")
case "$image_id" in sha256:*) ;; *) echo 'Image identity unavailable' >&2; exit 1 ;; esac
docker run --rm --network none --entrypoint python \
  -e PYTHONPATH=/audit/src \
  -v "$repo:/audit:ro" "$image_id" \
  -m unittest discover -s /audit/tests -v
docker run --rm --network none --entrypoint python \
  -e PYTHONPATH=/audit/tests/integration:/yamtrack \
  -v "$repo:/audit:ro" \
  -v "$repo/src/kavita_yamtrack_sync:/yamtrack/kavita_yamtrack_sync:ro" \
  -v "$repo/deploy/django_management:/yamtrack/app/management:ro" \
  "$image_id" /audit/tests/integration/run.py
printf 'Compatibility tests passed for immutable image %s\n' "$image_id"
