# TypeSafe Jev shadow experiment

Enable SHOPPING_JEV_MODE=shadow with TYPESAFE_SECRET_FILE pointing to an external owner-protected file mounted at /run/secrets/typesafe_api_key. No secret belongs in Git, environment values or data backups. Default off.

Only product names absent from the exact offline food dictionary are submitted, after the draft is shown. Rules and user categories remain unchanged. One background worker, at most eight admitted tasks, and at most 100 reserved attempts per UTC day, persisted in SQLite. At capacity, skip experimentation. No retries. API errors do not affect shopping. Existing manually assigned categories are compared as baseline, not replaced and not considered ground truth.

API: https://api.typesafe.ai/v1/systemone ; official schema: https://docs.typesafe.ai/api . Model alias jev-latest; actual returned model saved. Choice between the app's 15 categories. Response bounded to 64 KiB; timeout 10 seconds. Only product name sent; no user identifiers, notes, audio or entire lists. Telemetry stores draft ID/item key and category labels, not names or transcripts.

Owner-only /api/admin/jev and dashboard show latest 100 rows and 90-day aggregate usage. Estimated USD = returned input_tokens × $0.042 / 1,000,000; output charge assumed zero per published rate checked 2026-10-09. Source: https://typesafe.ai/blog/introducing-system-one-models-and-jev . This is not actual billed balance and excludes credits, discounts and future tariff changes. Failures without valid usage have unknown cost, not zero cost. Rows retain input/output tokens, latency, actual model and build identity. Confidence and agreement with rules are not accuracy. A restart may leave pending rows; the experiment queue is not durable.

Full all-provider AI spend dashboard is separate work; this view measures Jev only.
