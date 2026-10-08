# Abuse protection

Protection is process-local and intended for this single-instance deployment.
Limits reset after restart. A distributed deployment needs shared admission/rate
limits; these controls do not stop a distributed denial-of-service attack.

- Bot container: 3 GB RAM, no additional swap allowance, at most two CPUs and
  128 processes. A runaway process cannot consume all host memory.
- Telegram: per identity, burst 30 updates, replenishing one per second. Excess
  updates are ignored to prevent reply amplification.
- Authenticated HTTP API: burst 100 reads, two per second; burst 30 writes,
  one per two seconds. Excess requests return 429 before changing data.
- HTTP: 32 active handlers, 10-second socket inactivity timeout, 10 KB JSON body.
- Notification executor: 64 running/queued jobs; shopping writes return 429 before
  committing when this queue is full. Saved changes keep their notifications.
- Voice: burst six admissions, replenishing one per minute, at most two pending
  jobs per user and 20 globally, including the running job. Slots release even on
  failure. Audio is capped at two minutes after bounded conversion; Whisper gets
  a five-minute execution deadline. Overlong audio is rejected rather than saved
  as a truncated shopping list.
- Product photo uploads: burst five, replenishing one per five minutes; each
  downloaded photo is capped at 5 MB. Existing stored photos remain unchanged.

Remaining limits: many distinct legitimate Telegram accounts can still consume
storage or compete for resources. Monitor disk space and latency; use edge rate
limits and storage quotas before broad public promotion. A stable HTTPS domain is
also preferable to the current temporary tunnel address.
