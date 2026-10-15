> Archived 2026-10-15. The live guide is `src/shopping_bot/help.json` (text) + `src/shopping_bot/web/help.js` (mockups); this prototype is kept only as approval history and is not updated.

# Help design — approval draft

Scope: a standalone review prototype; no production files, commands, database or
VPS configuration are changed. Both Ukrainian and English are hand-written in the
prototype. Six steps, two roles and language switching are interactive.

## Direction

Reuse the product's Onest headings, Manrope body and purple action color. Palette:
background #F7F7FA, surface #FFFFFF, ink #20202B, muted #686878, action #6544E8,
annotation #EF713E. Orange is reserved for arrows and the next control to tap.
One action per screen. Illustrations are labelled diagrams, not live screenshots;
Telegram layout differs by platform. No unrelated decorative animations.

## Proposed implementation after approval

- /help and “How to use” in the bot open the quick-start guide in the user's language.
- Show a short first-launch hint, with independent creator/invited paths.
- Preserve an incoming invitation when opening Help; guide cannot consume or replace it.
- Keep a text-only bot fallback with the same instructions.
- Add “Help” to the Mini App; closing it returns to the current list.
- “Family · 2” is a sample for a couple; real families may have more members.
- Match illustrations and translated button labels to the actual UI before release.

Approval covers content, two-path structure and visual style. Implementation and
production deployment happen only after explicit approval of this draft.

## Revision: Telegram style

Following feedback, the guide is now presented as a Telegram-like conversation:
white message bubbles, blue inline buttons, a bot header and chat background.
Illustrated controls retain arrows. Instructions explicitly distinguish actions in
the bot from the shopping checks and product notes in the Mini App. This remains
an approval prototype; no live bot changes are deployed.

## Screenshot-style revision

Illustrations now include Telegram status/header, chat background, message times,
inline button rows and input bar. Orange callouts sit over the relevant control.
Every illustration is labelled as a screenshot mockup with sample data; it is not
a captured production screen. Actual device screenshots can replace these after
the flow and content are approved. Both languages remain available.
