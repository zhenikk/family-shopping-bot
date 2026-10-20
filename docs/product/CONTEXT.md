# Grocery Bot — product context and design brief

Updated: 2026-10-14. Audience: product designers, contributors, and AI assistants.

This document records owner intent, conversation examples, and repository evidence.
It is not evidence that a feature is deployed or validated with users. Check the
release, code and tests before making public claims. No interviews or quantitative
research have been conducted for this document.

## 1. Product in one sentence

Turn everyday voice or text requests into a clear, current shopping list in
Telegram, so people remember what to buy and avoid buying the same thing twice.

Public bot: @ggrocery_bot. Working name: Grocery Bot. Repository:
https://github.com/zhenikk/family-shopping-bot.
Naming alternatives discussed by the owner are not an agreed rebrand.

## 2. Origin and audience

The owner and his wife live in Portugal. Shopping requests arrive as Telegram
voice messages; finding and remembering products inside those messages is awkward.
They shop in Mercadona, Lidl and Auchan. Product photos help the person shopping
identify the exact package. The product now also serves people shopping alone and
small groups sharing a list. Public beta is an ambition, not proof of scale.

Users already know Telegram. Installing a separate app is additional friction.
The primary task is remembering purchases; family setup must not dominate it.

## 3. Problem / response / validation register

| ID | Pain or job | Intended response | Evidence and remaining question |
| --- | --- | --- | --- |
| P01 | Requests disappear in chat history | Voice/text → editable preview → active list | Original owner problem; measure time to first successful list |
| P02 | Conversational words become products | Extract products, preserve useful details, discard greetings | Owner example produced “Женя”, “Дякую”; rules and optional extraction exist; natural language coverage remains imperfect |
| P03 | Different words create duplicates | Canonical aliases and explicit duplicate review | Owner examples “картошка/картопля”; never merge distinct dietary variants |
| P04 | Shopper cannot identify the right package | Persistent reference photo and product note | Explicit owner need; usability of taking/finding a photo needs testing |
| P05 | Someone buys what their partner already bought | Shared active list, purchase history, grouped notifications | Owner reported invisible shared products; verify membership and cross-client refresh |
| P06 | Quantity gets lost or replaces useful details | Editable quantity in notes, retain descriptive notes | “Дві пачки масла”; show current/proposed note on duplicates |
| P07 | Long list is difficult to scan in store | Aisle categories, readable product names, fast purchase action | Owner requested Bring-like categories; do not require starting a shopping session |
| P08 | Bot chat becomes cluttered | Reuse current panels, avoid repeated menus and onboarding | Repeated help steps and old keyboards confused the owner |
| P09 | Solo users feel forced into family setup | Immediate personal list, optional sharing later | Owner reports solo-user confusion; avoid making solo/shared the marketing headline |
| P10 | Existing personal list blocks joining another | Explicit join/transfer preview and confirmation | Real onboarding report; never silently merge or delete other people's data |
| P11 | Notification preview is unreadable | One purchase summary, few item names, remaining count | Owner screenshot had a checkmark before every item; new format proposed, not shipped |
| P12 | Adding while hands are busy is awkward | Voice bot input; experimental iOS Shortcut | Siri recording/language failures reported; physical-device reliability unresolved |
| P13 | Bugs are difficult to reproduce | In-bot support, release identity, owner diagnostics | Implemented foundations; do not expose private content in public reports |
| P14 | Requests happen in another conversation | Reply with bot mention, private preview and confirmation | Guest handler exists; ordinary bot link alone does not supply message context; verify deployed Telegram behavior |

These are owner needs and reported incidents, not market-size or retention evidence.

## 4. Core journeys and invariants

### Capture

Send voice/text → wait only if necessary → inspect recognized products and notes →
edit/remove mistakes → confirm → see the updated list. Never silently turn uncertain
speech into irreversible writes. Keep names, quantities, variants and notes visible.

### Shop

Open the active list directly → scan categories → inspect a photo/note if needed →
mark bought → item disappears for all members → allow undo. Catalog metadata remains
available for the next purchase. Opening a product must not hide its full name.

### Share

Personal list works immediately. Invitation is optional and one-use. Joining another
list requires informed confirmation, especially if an existing list contains data.
All members should see the same active needs. Authorization follows current membership.

### Explicit purchase command — in progress

“Купив молоко, яйця” / “Bought milk” → match active products → purchase preview →
confirm selected items → record purchases once. Unknown products must not be created.
“Не купив” must not mark purchased. Mixed intentions require clarification.
Local implementation exists in the working tree; do not describe as released yet.

### Release announcements — in progress

Owner writes announcement → previews exact text and audience → explicitly approves →
send once per recipient with delivery accounting. Deployment alone never authorizes a
broadcast. Current working-tree implementation needs review/testing before release.

## 5. UX direction and known decisions

- Lead with “remember what to buy”, easy capture and an up-to-date list.
- One active list across stores. Store-specific requests belong in notes.
- Bot and Mini App are two surfaces for the same list, not separate products.
- Bot: quick capture, confirmation, lightweight list actions, support, notifications.
- Mini App: richer visual browsing/editing; exact division of responsibilities is
  still a design question. Do not remove it or force it without a reviewed proposal.
- Ukrainian, English and German UI (German added 2026-10-20, 0.5.44); saved language preference should apply consistently.
- Display product names with initial capital; categories visually distinct.
- Avoid repeated onboarding for returning users and duplicate current panels.
- Prefer compact notifications: “Оля купила 6 товарів\nМолоко, виноград, йогурт + ще 3”.
  Inside the chat, show the full purchased list and access to the active list.
- Group related purchase notifications; avoid one push per product.
- Exact visual identity, type system and final product name remain open.

## 6. Implementation context

Python, direct Telegram Bot API, SQLite with per-family data isolation, Telegram
Mini App, Docker Compose on a small Ubuntu VPS. Groq transcription with local
whisper.cpp fallback/optional race; optional DeepSeek product extraction with local
rule fallback. Open Food Facts-derived dictionary supplies category vocabulary.
TypeSafe Jev is a shadow categorization experiment, not an established accuracy win.

The original recurring budget target was around €5/month. Avoid adding infrastructure
or AI calls without a measurable benefit. Keep API credentials outside Git. Do not
promise supported user counts without load measurements. Voice/API failures should
preserve user data and offer a comprehensible recovery path.

Operational details: ../../README.md, ../production-runbook.md,
../production-roadmap.md. These documents can contain older assumptions; verify
runtime configuration. Release evidence: ../../CHANGELOG.md and Git tags.

## 7. Deferred ideas — not product promises

Receipt OCR and price history/comparison; consumption-based reminders; native mobile
app and native voice integrations; geofenced store notifications. Owner explicitly
prioritized manual store/list access over location automation and deferred receipts.
Do not describe these as available features.

## 8. How to evaluate a redesign

Proposed metrics (not currently established baselines):

- Time and steps from first start to confirmed first product.
- Share of voice drafts requiring name, quantity or variant correction.
- False duplicate merges and unnecessary duplicate products.
- Time to find and mark a product bought; accidental purchases and undo success.
- Cross-member list consistency and update latency.
- Number of bot messages/pushes per capture or shopping batch.
- Transcription latency p50/p95, queue wait, provider failures and cost per request.

Review empty/loading/error/offline states, long names, 1 vs 50 products, two people
editing simultaneously, stale buttons, replayed confirmation, language changes and
returning users with old keyboards. Include Ukrainian and English examples.

## 9. Request for a designer / Claude

Read this brief, inspect actual UI/code and relevant release notes, then identify
which problems are observed and which are hypotheses. Propose the five highest-impact
improvements, concrete bot messages/buttons and Mini App wireframes. Explain what
each change solves, failure states, Telegram limitations, and how to measure it.
Prioritize a coherent capture → review → shop loop over adding features.
Do not modify code or announce unshipped features until the proposal is reviewed.
