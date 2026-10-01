# Mini App: typography and visual design

Updated 2026-10-01. Audience: two family members buying groceries in Portugal. The main job is recognizing the correct product and marking it bought with one thumb.

## Direction

Rounded, confident headings, quiet graphite surfaces and one expressive violet action color. Instagram’s 2026 brand refresh describes updated Instagram Sans, Instagram Pen and Instagram Mono; the design references their expressive typography, without including Meta’s brand typefaces or logos. [Meta: new Instagram brand identity](https://www.meta.com/design-at-meta/blog/the-new-instagram-brand-identity/)

- **Onest:** headings, product names and navigation. **Manrope:** notes, search and forms. Both are distributed locally in WOFF2 with their OFL license files; the Ґ/ґ/Є/є/І/і/Ї/ї glyphs were checked in the font character maps, rather than requesting fonts from a runtime CDN. [Onest metadata](https://github.com/google/fonts/blob/main/ofl/onest/METADATA.pb), [Manrope source and license](https://github.com/google/fonts/tree/main/ofl/manrope)
- Palette: milk `#F7F7FA`, white `#FFFFFF`, graphite `#191920`, muted `#666676`, violet `#6544E8`, violet wash `#EEEAFB`. Dark theme: charcoal `#101014`, elevated `#1B1B22`, lavender `#B8A4FF`.
- One consistent set of inline SVG icons replaces platform-dependent symbols in the main navigation, search and toolbar.
- Product names carry the strongest weight; notes remain readable below them; counts stay beside category headings. Large 44px check controls retain distinct unselected and selected states.
- Product cards and adding forms appear as bottom sheets, with a visible close button and Telegram Back support.
- Motion: a short sheet entrance, active navigation settling, check drawing and row dismissal. Reduced-motion preferences disable animation. Purchase feedback starts before the network response and rolls back if unconfirmed.

## Design decisions

Script lettering is suited to an occasional brand mark; product names and instructions need readable Ukrainian sans lettering. Avoided using a multicolor gradient across every control: one violet action color communicates what can be pressed. Color is not the only purchase cue: the check draws and the product leaves the active list.

Verified in mobile browser scenarios at 320px and 390px, light/dark themes, adding, notes, purchase, undo and simulated network failure. Actual Telegram phone testing remains useful for device-specific keyboard and safe-area behavior.
