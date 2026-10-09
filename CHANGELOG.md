# Changelog

## 0.5.11 — 2026-10-09

- Preserve dietary product variants before name deduplication in extraction, text parsing and draft creation; regular and lactose-free milk remain separate.
- Add a natural-language QA corpus, duplicate lifecycle/ownership/replay tests and malformed extraction response tests. Fix local parsing of explicit negations, corrections, English packaging and semicolons in notes.
- Normalize творог to Сир кисломолочний so it is categorized as dairy.


## 0.5.10 — 2026-10-09

- Extract Ukrainian/English quantity prefixes into editable product notes and retain existing descriptive notes when replacing an amount.
- Show current/proposed notes for active duplicates with edit and keep controls; apply only on confirmation. Ask to review again if another user changed the note.


## 0.5.9 — 2026-10-09

- Bold category names in Telegram shopping lists, drafts and product cards, including shared list refreshes.
- Escape product names and notes and preserve complete HTML blocks within message limits.

## 0.5.8 — 2026-10-09

- Add opt-in TypeSafe Jev shadow categorization for names absent from the offline dictionary, without updating user categories.
- Add private experiment timing, confidence, token usage and estimated cost dashboard with bounded background work and 100 attempts per UTC day.
- Read TypeSafe credentials from an external Docker secret.

## 0.5.7 — 2026-10-09

- Add opt-in first-success Groq/local race with one bounded local Whisper slot; skip local samples when busy.
- Add owner-only per-message timing comparison, statuses and normalized transcript agreement with 90-day retention and release identity. No transcript content is stored.

## 0.5.6 — 2026-10-09

- Send an application User-Agent on speech and extraction requests; fixes Groq rejecting Python default requests with HTTP 403.

## 0.5.5 — 2026-10-09

- Add opt-in Groq Whisper Large v3 Turbo transcription with a mounted credential, bounded responses and local Whisper fallback.
- Retain duration limits, Ukrainian/English preference and one worker during initial rollout.

## 0.5.4 — 2026-10-09

- Load production DeepSeek credentials from a read-only Docker secret outside the repository and data backups.
- Exclude local secrets from Git and image build contexts.

## 0.5.3 — 2026-10-09

- Fix generated English admin translations that broke the locale consistency CI gate.
- Add opt-in text-only DeepSeek extraction for voice shopping drafts with bounded JSON validation, timeout and local-rule fallback. Voice notes remain local.

## 0.5.2 — 2026-10-09

- Keep one local Whisper worker and expose bounded queue wait/workflow latency metrics to the owner dashboard in Ukrainian and English.
- Track active/waiting/rejected jobs without storing voice content; metrics reset on restart.

## 0.5.1 — 2026-10-09

- Filter conversational shopping introductions, politeness and trailing urgency before creating draft items.
- Preserve trip store and packaging details in notes, and keep unknown product names available for correction.
- Add a copy-name button to draft renaming prompts in both languages.

## 0.5.0 — 2026-10-09

- Add a standalone 11,024-entry Ukrainian/English/Portuguese Open Food Facts category dictionary (ODbL).
- Supply bounded local shopping vocabulary hints to Whisper; keep free-form voice notes unprompted.
- Introduce 15 shopping aisle categories, including snacks, spices, pets, home and car supplies.
- Reclassify existing catalog items and drafts once, preserving subsequent manual category choices.
- Correct toothpaste, meat spelling, avocado variants and frozen-food context matching.
- Update category labels in Ukrainian and English across bot and Mini App.

## 0.4.1 — 2026-10-09

- Fix guest mentions replying to text shopping lists: use the referenced text when the mention has no items.
- Add content-free guest delivery diagnostics.

## 0.4.0 — 2026-10-09

- Support Telegram Guest Mode text and voice replies using the existing local speech queue.
- Keep item previews and confirmation in the caller’s private bot chat; guest chats receive only a generic acknowledgement.
- Require an existing list and preserve rate limits and family isolation.

## 0.3.0 — 2026-10-09

- Add “Just for me” and “With others” choices to Telegram and Mini App onboarding.
- Personal lists start immediately, with all shopping features and optional invitations later.
- Use neutral shopping copy and explain that one-person lists are fully supported.
- Update Ukrainian/English help and illustrations for optional sharing.

## 0.2.1 — 2026-10-08

- Fix “List in chat” appearing unresponsive: explicit opening sends the current list to the bottom and removes the previous tracked panel; purchase callbacks continue editing in place.
- Accept the list button from an older Ukrainian/English keyboard after changing language.

## 0.2.0 — 2026-10-08

First versioned release of the existing beta. Earlier deployments are identified by Git commit only.

- Add immutable version and Git revision to support tickets, analytics events, runtime logs, admin UI, and `/version`.
- Add a release filter to the admin event journal.
- Keep one persistent help panel and reuse shopping list messages.
- Skip initial onboarding for existing family members.
- Ukrainian/English illustrated help with paths for creating and joining a family.

Existing features include shared family shopping lists, voice recognition with whisper.cpp, product photos and notes, purchase history, Telegram Mini App, and owner-only support and analytics.
