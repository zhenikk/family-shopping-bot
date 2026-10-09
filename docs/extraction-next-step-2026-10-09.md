# Extraction next step

Recommendation: evaluate DeepSeek Flash non-thinking via API, rather than hosting another NLP model on the current 2 CPU / 4 GB VPS. This is a candidate, not a verified accuracy improvement. Keep Whisper local, one worker. No external API has been activated and no user text has been transmitted.

Official pricing checked 2026-10-09: https://api-docs.deepseek.com/quick_start/pricing/
`deepseek-flash`: uncached input $0.15–0.30/M tokens, output $0.60–1.20/M, depending on hours. Assumed 500 input +150 output tokens: $0.000165–0.00033/request, or $1.65–3.30 per 10,000 requests. Real Ukrainian token usage must be measured. Network latency, availability and privacy tradeoffs remain.

Minimal pipeline: local Whisper → external text extraction into JSON → local validation/category IDs/deduplication → existing confirmation draft. Preserve notes; exclude negation, already bought items, greetings, store trip chatter. Never execute model instructions. Maximum input/output size, timeout and monthly spend cap; fall back to existing rules with clear confirmation on errors. No photos, audio, names or Telegram IDs need to be sent. Explain transcript processing in privacy/help before enabling for beta users.

Before activation: configure secret API key server-side, run the same synthetic benchmark plus held-out corrections and negations; measure latency/tokens/cost. JSON correctness alone does not prove extraction correctness. User confirmation remains necessary. Avoid maintaining two model stacks until measured accuracy justifies it.

Queue metrics: bounded last 512 wait/workflow duration samples in memory, reset on restart. Admin-only API stats includes waiting/active/oldest wait, accepted/completed/rejected/unexpected failed counts, p50/p95. Existing voice_done/voice_error analytics retain recognition outcome history by release. Processing time covers full voice workflow including Telegram calls, not inference alone. One Whisper worker remains hard-coded.
