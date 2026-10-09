# Changelog

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
