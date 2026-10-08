# Production roadmap — 2026-10-08

Initial release target: one VPS and a controlled beta with tens of families.
The current CPU speech worker and per-family SQLite design are not validated for
mass adoption. Start with actual workload measurements rather than upgrading RAM
or promising a user count. Current observed VPS usage: 569 MB of 3916 MB RAM and
6.9 GB of 39 GB disk; that snapshot does not measure speech peak load.

## P0 — before a public beta

| Work | Acceptance condition | Status |
| --- | --- | --- |
| SSH access | Verified separate key-based administrator, no password/direct root SSH; tested rollback/recovery | Awaiting explicit confirmation after automatic security review blocked host changes |
| Network | Only SSH publicly exposed on host; firewall and SSH brute-force protection verified for IPv4/IPv6; Docker ports reviewed | Pending host change approval |
| Stable HTTPS | Own domain and named tunnel or reverse proxy; URL survives restart; Telegram menu works | Awaiting domain choice |
| Verified backups | Atomic private archives, SQLite integrity validation, retention; failed copy never removes the previous one | Implemented in this release |
| Independent recovery | Encrypted backup outside VPS, protected recovery key, successful restore to an empty instance, measured recovery time | Awaiting destination; local verification alone does not satisfy this gate |
| Health checks | Polling heartbeat and database query produce 503 when stalled; Docker reports unhealthy | Implemented in this release |
| Alerts | Independent check of public health, disk, backup age and container restarts; delivery to owner tested | Pending monitoring destination; no unsolicited messages configured |
| Deployment | Tests, pre-deploy backup, bounded health wait and previous-image rollback | Successful VPS deployment verified; failure/rollback paths tested with an isolated Docker fixture |
| Privacy controls | Explain collected metadata/retention; account deletion/export and family deletion behavior tested; invitations reviewed | Pending; analytics contains personal identifiers |
| Storage safeguards | Per-family photo/catalog limits, low-disk rejection, orphan photo cleanup; no loss of active referenced images | Pending; current file/rate limits do not cap lifetime storage |

Existing security controls: signed Telegram authentication, server-side admin
allowlist, locked membership checks and writes, isolated photos, one-use invites,
bounded HTTP/voice/notification workers, API throttling, media limits, non-root
read-only container with capability and CPU/RAM/process limits.

## P1 — beta reliability

1. Persist voice job state, recover interrupted jobs, show retry/cancellation and
   schedule fairly across families. Current queued jobs disappear on restart.
2. Remove slow Telegram calls from the global family lock while preserving current
   authorization guarantees. Measure list latency during voice and Telegram errors.
3. Add operation IDs for retry-safe writes and purchases; test network retries,
   duplicate updates and restart boundaries. Current idempotence coverage is partial.
4. Test concurrent purchases, family transitions, notification failures, disk full
   and process restart with realistic beta traffic. Define an observed capacity
   ceiling and reject excess work rather than let queues grow.
5. Make schema migrations versioned and distinguish reversible application rollback
   from database restoration; keep a supported previous-version upgrade path.
6. Add structured operational counters for rejects, queue depth, speech latency,
   backup age and disk usage. Keep text/audio/product contents out of logs.
7. Dependency and image vulnerability review plus an update procedure; CI tests do
   not substitute for a vulnerability scan.

## P2 — scale after measurements

- Shared queue, rate limits and object storage when there are multiple processes.
- PostgreSQL when measured SQLite contention/operations justify the migration.
- Separate speech workers and capacity planning; a GPU is not required for beta.
- Managed deployment/monitoring and documented incident-response ownership.

## Launch gate

Do not label the service production-ready until all P0 acceptance conditions are
met. Start an invite-only beta after recovery, privacy and monitoring are verified.
Targets to validate: daily independent backups (RPO <=24h), recovery within one hour
(RTO <=1h), useful alerts within five minutes, list operations under one second at
the agreed beta workload excluding speech. These are targets, not current guarantees.

## Completed first release

Release `1e24605` deployed on 2026-10-08. The bot is Docker healthy and public
`/healthz` returned 200. A new mode-600 production backup was extracted in an
isolated directory; five SQLite snapshots passed integrity checks. The release
adds health, private atomic backups, retention, CI gates and a deployment runbook.
An independent restore to a replacement server has not yet been performed.
