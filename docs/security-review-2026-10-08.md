# Security review — 2026-10-08

Scope: current Telegram bot, Mini App API, private analytics, family permissions,
file access, Docker configuration and read-only VPS inspection. This is a targeted
review, not a penetration test or a guarantee that every vulnerability is found.

## Fixed

- Family membership checks and data operations now share the registry lock. A
  concurrent leave, transfer or deletion cannot revoke membership between an API
  permission check and its write. HTTP response bytes are sent outside the lock.
  Telegram update handling and application of delayed voice results use the same
  lock. Invite revocation checks the current owner inside its write lock.
- HTTP requests have a 10-second socket inactivity timeout and at most 32 active
  handlers. Request bodies remain capped at 10 KB and are read before taking the
  family lock. Excess connections are closed; incomplete bodies receive 408.
- Both containers drop all Linux capabilities, have a 128-process limit, and
  rotate JSON logs at 10 MB with three files. Existing non-root bot execution,
  read-only filesystem and no-new-privileges remain in place.

## Existing controls inspected

- Every private API request verifies Telegram HMAC, session age and user identity.
  Admin endpoints additionally check a server-side allowlist.
- Family headers prevent stale-client writes. Invites are single-use and acceptance
  requires confirmation. Photo paths are restricted to the current media directory.
- Private responses use no-store; the app sets CSP and nosniff headers.
- Analytics stores event metadata rather than transcripts, products or credentials.
- The application port binds to loopback on the VPS. The environment file is mode
  600; the data directory is mode 700. The bot runs as an unprivileged container user.

## Remaining priorities

1. SSH currently permits root and password authentication. Establish and verify a
   separate administrator account with a key, then disable password login and
   direct root login. SSH settings were not changed during this review.
2. The voice executor has an unbounded queue and Whisper has no execution deadline.
   Public beta can exhaust disk/CPU or delay legitimate requests. Add a bounded
   queue, per-user fair scheduling and recognition timeout before broad promotion.
3. Daily backups are on the same VPS. Add encrypted copies on independent storage
   and test restoration. Local backups do not protect against loss of the VPS.
4. Legacy join-code compatibility remains; remove it when existing users have
   migrated to one-use invitations.

## Verification

50 isolated unittest cases passed, including signed-session failures, admin access,
family/photo isolation, invite concurrency, membership locking and incomplete-body
HTTP timeout. No production user impersonation was used. Deployment health should
be checked after rebuilding the containers.
