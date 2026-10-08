#!/usr/bin/env bash
# Run from the checked-out release on the VPS. Never restarts the HTTPS tunnel.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
revision=$(git rev-parse HEAD)
# Identify the actual built checkout. Refuse tracked edits that would break attribution.
git diff --quiet HEAD -- || { echo 'Commit tracked changes before deploying.' >&2; exit 1; }
version=$(PYTHONPATH=src python3 -c 'from shopping_bot import __version__; print(__version__)')
if git describe --exact-match --tags HEAD 2>/dev/null | grep -Fxq "v$version"; then
  release="$version"
else
  release="$version-dev+${revision:0:12}"
fi
container=$(docker compose ps -q bot)
if [[ -z "$container" ]]; then
  echo 'Expected an existing bot deployment; use the installation procedure first.' >&2
  exit 1
fi
previous_image=$(docker inspect "$container" --format '{{.Image}}')
docker tag "$previous_image" family-shopping-bot-rollback:previous
docker compose exec -T bot python -m shopping_bot.backup --data-dir /data --output-dir /data/backups
changed=0
rollback() {
  trap - ERR
  if [[ "$changed" == 1 ]]; then
    echo 'Deployment failed; restoring the previous application image.' >&2
    docker tag "$previous_image" family-shopping-bot-bot:latest
    docker compose up -d --no-build --no-deps --force-recreate bot
  fi
  echo 'Database was not restored automatically; inspect migration compatibility before rollback.' >&2
  exit 1
}
trap rollback ERR
docker compose build --build-arg "APP_COMMIT=$revision" --build-arg "APP_RELEASE=$release" bot
changed=1
docker compose up -d --no-deps bot
healthy=0
for attempt in $(seq 1 18); do
  if docker compose exec -T bot python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=5).read()" >/dev/null 2>&1; then
    healthy=1
    break
  fi
  sleep 5
done
if [[ "$healthy" != 1 ]]; then
  false  # Trigger rollback.
fi
docker compose exec -T bot python -c 'import sys; from shopping_bot.version import release; assert release() == {"version":sys.argv[1],"commit":sys.argv[2]}, "Running image identity differs from release"' "$release" "$revision"
printf '%s %s %s\n' "$(date -u +%FT%TZ)" "$release" "$revision" >> data/deployments.log
echo "Healthy release: $release ($revision)"
