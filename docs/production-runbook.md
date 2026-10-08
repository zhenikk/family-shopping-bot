# Production operations

Run commands from `/opt/family-shopping-bot` on the VPS.

## Health

`docker compose ps` should report the bot healthy. `/healthz` returns only a coarse
status; it checks the registry and a Telegram polling heartbeat (120-second limit,
including startup grace). It does not test speech quality, restore capability or
Telegram delivery. Docker marks unhealthy but does not automatically restart a
running unhealthy container. Independent alerts are still required.

## Release

1. Run CI and inspect the change, especially schema/data migrations.
2. Fetch and check out the intended revision on the VPS.
3. Run `bash scripts/deploy.sh`. It validates a backup, retains the previous Docker
   image, builds the release, restarts only the bot, checks health and rolls back the
   application image if health does not recover.
4. Verify public `/healthz`, Telegram menu, language, a test-family purchase and
   shared-list visibility. Do not use another user's Telegram credentials.

The single instance has a brief restart outage; in-memory queued voice jobs are
lost. Automated image rollback does not restore the database. For schema changes,
confirm backward compatibility before using this deployment procedure.

## Backup and recovery drill

`docker compose exec -T bot python -m shopping_bot.backup --data-dir /data --output-dir /data/backups --keep 14`

A copy is published only after extraction to an isolated private directory and
integrity checks of every SQLite snapshot. Retain 14 successful archives, rather
than 14 calendar days; deploy/manual copies count. Archives use mode 600. Verification
rejects traversal, symlinks, duplicates, missing family databases and oversized
archives (2 GB expanded maximum). Temporary verification files use the backup disk,
not the container's small /tmp tmpfs.

`docker compose exec -T bot python -m shopping_bot.backup --verify-archive /data/backups/ARCHIVE.tar.gz`

For a full recovery drill, use an empty instance and an independent encrypted copy.
Stop the bot before a real restore; restore databases and photos together into the
original `/data` layout (photo paths are absolute). Preserve original numeric
ownership (10001), keep configuration/token separate and verify family isolation,
counts, photos and polling offset. Never extract an untrusted archive as root.
Current automated verification validates the snapshots, not the complete recovery
of the service on a replacement machine.

## Incident response

- Suspected token leak: rotate via BotFather, replace the VPS secret, restart only
  the bot, invalidate old signed launches and review access. Never paste tokens in
  logs, Git or support messages.
- Bad deployment: use previous image; restore a database only after stopping writes
  and explicitly reviewing potential data loss since the backup.
- High load: inspect queue/CPU/disk, pause public invitations and reduce expensive
  work. Keep shopping-list reads available where possible.
- VPS compromise: rebuild from a clean image, rotate credentials and restore from
  an independent known-good copy. A backup stored only on that VPS is insufficient.
