# Mini App: visual system

Updated 2026-10-19 (supersedes the 2026-10-01 note). Audience: two people buying groceries in Portugal, one-handed, in a store. The main job is recognizing the right product and marking it bought with one thumb.

## Direction

The app follows the user's own Telegram theme: `bg_color`, `secondary_bg_color`, `text_color`, `hint_color`, `button_color` and `button_text_color` from `themeParams` overwrite six CSS tokens (`--surface`, `--bg`, `--text`, `--muted`, `--accent`, `--on-accent`); lines and tinted surfaces derive from them with `color-mix`. Outside Telegram (demo, tests) the fallback is paper `#f1f2f6`, white, ink `#16171d`, muted `#6c7082`, violet `#6544e8`; dark fallback `#111216` / `#1c1d23` / lavender `#b4a4ff`. The header and page colors are handed to Telegram with `setHeaderColor`/`setBackgroundColor`.

- **Onest** for the title, category headings and product names; **Manrope** for everything else. Both ship locally as WOFF2.
- One bold element: the round check at the right edge of every row, a 30 px ring inside a 52 px target that fills with the accent and strikes the name when tapped. Everything else is quiet: no shadows except under the add button, no all-caps labels, no decorative eyebrows.
- Radius encodes hierarchy: sheets 20 px, lists 14 px, thumbnails 10 px, chips and checks round.
- Density: rows are 64 px (40 px thumbnail, name 16/600, one-line note 13 px), so a phone shows seven to eight products under the sticky search and category chips.
- Thumb zone: the add button is a 56 px floating button above the tab bar; the tab bar has four tabs (Shopping, Catalog, History, More). Search and chips stay at the top while the list scrolls.
- Sheets open from the bottom with a drag handle, swipe down to close, Telegram Back support, and the primary action pinned above the keyboard and the home indicator. In the product card the first action is Bought (or Add to list), then Save changes.
- Motion only answers a tap: the check pops and the row slides out; sheets rise; reduced-motion disables all of it.

## Checked

Demo mode (`?demo=1`) at 375×812 and 320×640, light and dark, in a desktop browser: list, product card, add sheet, buying state, undo toast, More tab, help and family sheets. Real Telegram clients still need a device check for the keyboard, safe areas, `themeParams` colors and the camera file input.
