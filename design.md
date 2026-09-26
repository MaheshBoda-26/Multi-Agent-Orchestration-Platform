# Design System — Apple.com Web Language (Research Doc)

> Purpose: a complete, implementation-ready specification of the design system used by
> apple.com, researched for the Orchestra rebuild. This document is research only —
> no implementation code lives here. It is the contract any future build must follow.

---

## 1. Design Direction Summary

| Field | Value |
|---|---|
| **Aesthetic name** | *Cupertino Precision Minimalism* — confident, restrained, hardware-grade clarity |
| **DFII score** | **13 / 15** — Impact 5, Context Fit 4, Feasibility 5, Performance 4, Consistency Risk 1 |
| **Key inspiration (conceptual)** | Dieter Rams' "less, but better" applied to a retail page; editorial print discipline (one idea per screen) combined with photographic full-bleed product imagery |
| **Tone** | Luxury-minimal + editorial. Exactly two directions, never more. |
| **Differentiation anchor** | If the logo were removed, people would still recognize it from: (1) SF Pro set tight at huge sizes, (2) the `#f5f5f7` → white → black section rhythm, (3) pill CTAs with chevron "Learn more" links, (4) the 44px translucent blurred global nav. |

**Purpose of the site:** persuasive + functional. It sells trust first (hero, numbers, story), then lets the user act (dispatch a task inline). For Orchestra, Apple's language says: *this infrastructure is as considered as the product it runs.*

**What users should feel in the first 3 seconds:** calm confidence. Nothing moves yet, everything is perfectly aligned, the type is doing all the talking.

---

## 2. Research Sources

| Source | What was extracted |
|---|---|
| apple.com homepage (live HTML/CSS inspection) | Font loading (`/wss/fonts?families=SF+Pro,v3`), 44px globalnav, section rhythm, tile layout |
| developer.apple.com/design/resources | Official fonts (SF Pro, SF Compact, SF Mono, New York), SF Symbols naming, HIG structure |
| Apple Human Interface Guidelines (design/human-interface-guidelines) | Type scale philosophy, motion principles, accessibility requirements |
| apple.com product pages (iPhone / Mac) | Scroll-driven narrative patterns, sticky sections, spec tables, mega-footers |

---

## 3. Core Design Principles (the "why" before the "what")

1. **One idea per screen.** Every full-viewport section communicates exactly one message. No section carries two headlines.
2. **Typography is the UI.** Borders, boxes, and chrome nearly vanish. Scale, weight, and whitespace establish hierarchy — not containers.
3. **Elevated neutral canvas.** Content lives on white, `#f5f5f7` light-gray, or pure black. Color is reserved for the accent blue and the product imagery itself.
4. **Motion is narrative, not decoration.** Things animate because the user scrolled past a beat in the story, not because elements can wiggle.
5. **Invisible grid, visible precision.** Everything aligns to a strict column grid that the user never sees; alignment errors of 1px read as "broken Apple clone."
6. **Confidence through restraint.** No gradients on text containers, no shadows-as-decoration, no rounded-corner noise. Every visual element passes the "does removing it make this worse?" test.

---

## 4. Typography

### 4.1 Typefaces

| Role | Face | Rationale |
|---|---|---|
| **Display (≥20px)** | **SF Pro Display** | Apple's variable-cut display face; tight apertures, engineered for large sizes |
| **Text (<20px)** | **SF Pro Text** | Looser counters, wider apertures — legible at body sizes |
| **Code / mono (Orchestra data)** | **SF Mono** | Mirrors JetBrains Mono usage in the current console; Apple's Xcode face |
| **Serif accent (optional, quotes only)** | **New York** | Apple's reading face; used extremely sparingly on marketing copy |

**Font loading (as apple.com does it):** SF Pro is served as webfont, NOT system-dependent — apple.com loads it for all platforms. Two legal routes:
- `font-family: -apple-system, "SF Pro Text", ...` (native on Apple devices, falls back elsewhere)
- Download SF Pro / SF Mono from Apple Design Resources and self-host webfont files (what apple.com effectively does via `/wss/fonts`)
- Fallback stack apple.com uses verbatim:
  `"SF Pro Text","SF Pro Icons","Helvetica Neue","Helvetica","Arial",sans-serif`
  (Display swaps `SF Pro Text` → `SF Pro Display`.)

### 4.2 Optical-sizing rule

Apple swaps Text ↔ Display at the **20px boundary**. Above 20px → SF Pro Display. This single rule is one of the biggest tells of an authentic Apple look.

### 4.3 Type scale (measured from apple.com)

| Token | Size / Line-height | Weight | Letter-spacing | Use |
|---|---|---|---|---|
| `display-hero` | 80px / 1.05 | 600 | -0.015em | Homepage takeover headline (mobile: 40px) |
| `display-1` | 56px / 1.07 | 600 | -0.015em | Section H1 |
| `display-2` | 48px / 1.08 | 600 | -0.015em | Sub-section headline |
| `display-3` | 40px / 1.10 | 600 | -0.01em | Tile / card headline |
| `headline-small` | 32px / 1.13 | 600 | -0.01em | Mobile-first section headline |
| `subhead` | 21–28px / 1.14–1.24 | 400–500 | -0.01em | The gray line under the headline |
| `body` | 17px / 1.47 | 400 | -0.022em | All reading text |
| `body-enhanced` | 19px / 1.42 | 400 | -0.01em | Lead paragraphs |
| `caption` | 14px / 1.43 | 400 | -0.01em | Footnotes, legal, eyebrow labels |
| `nav-text` | 12px / 1.33 | 400 | 0 | Globalnav, footer links |

### 4.4 Typographic rules

- **Eyebrow labels** above hero headlines: 21px semibold, often in accent blue or a vivid color, title-cased ("New", "MacBook Pro").
- Headlines max ~8 words. Apple headlines are short enough to be set huge.
- Never justify text; always left-align or center (center for heroes, left for editorial sections).
- Never use letter-spacing above 0 except in all-caps eyebrows (rare on apple.com; +0.05em when used).
- Line-length: prose is constrained to ~680px even on wide screens.

---

## 5. Color System

### 5.1 Core palette (measured values)

| Token | Hex | Role |
|---|---|---|
| `surface-canvas` | `#fbfbfd` | Page background (near-white, faintly cool) |
| `surface-raised` | `#f5f5f7` | The signature Apple light-gray section fill — **the #1 most recognizable token** |
| `surface-inverse` | `#000000` | Full-bleed dark sections (product drama) |
| `text-primary` | `#1d1d1f` | Headlines and body on light |
| `text-secondary` | `#6e6e73` | Subheads, captions, footer |
| `text-tertiary` | `#86868b` | Fine print, disabled |
| `text-on-inverse` | `#f5f5f7` | Light text on black sections |
| `accent` | `#0071e3` | The Apple blue — buttons, links, product accent |
| `accent-hover` | `#0077ed` | Button hover state |
| `link` | `#06c` | Inline text links on light |
| `link-inverse` | `#2997ff` | Links on dark backgrounds |
| `hairline` | `#d2d2d7` | Dividers on light |
| `hairline-inverse` | `#424245` | Dividers on dark (e.g., footer on black) |
| `good / warn / bad` | `#34c759` / `#ff9f0a` / `#ff453a` | System semantic hues (used for Orchestra status data only) |

### 5.2 Color rules

1. **One accent, total discipline.** Blue `#0071e3` is the only interactive color. Nothing else tints UI chrome.
2. Statistically, an Apple page is ~90% neutral, ~8% photography, ~2% blue. Hold those ratios.
3. Dark sections are for drama (hero moments, spec reveals), alternating with light — never more than 2 consecutive dark sections.
4. Gradients appear ONLY as full-bleed photographic fades (image into black), never as CSS candy behind text.
5. Status/error colors come from the iOS system palette and are reserved for data (Orchestra run states), never decoration.

---

## 6. Spacing & Layout

### 6.1 Rhythm

- Base unit: **8px** (4px allowed at micro level: icon gaps, nav).
- Section vertical padding: **100–140px** desktop for editorial sections; **60–80px** mobile. This generous air is non-negotiable — it's where the "premium" feeling comes from.
- Headline → subhead gap: 12–19px. Subhead → CTA gap: 20–28px. These micro-rhythms must be consistent site-wide.

### 6.2 Containers

| Container | Max-width | Use |
|---|---|---|
| Full-bleed | 100vw | Hero imagery, tile sections |
| Editorial | ~980px | Centered headlines + prose (classic Apple measure) |
| Wide | ~1200–1400px | Product grids, spec comparisons |
| Nav content | ~1024px | Globalnav inner alignment |

### 6.3 Grid

- 12-column fluid grid inside containers, gutters ~20–24px.
- Asymmetry is achieved by **centering big and letting one element break the container** (e.g., a device image overflowing its column), not by chaotic offset layouts. Apple's asymmetry is quiet.

### 6.4 Corner radius

- Cards / tiles: **18px** (some store tiles 20px).
- Buttons: fully rounded pills (`border-radius: 980px`).
- Inputs: 8–10px.
- Nothing else gets a radius without asking why.

---

## 7. Navigation

### 7.1 Global nav (the header)

- Height: **44px** (48px compact mobile).
- Background: dark translucent — `rgba(22, 22, 23, 0.8)`, with `backdrop-filter: saturate(180%) blur(20px)`. On light pages some Apple projects use `rgba(251,251,253,0.8)` + dark text; choose one and be consistent. For Orchestra: **dark translucent nav always** — it reads as "instrument."
- Link style: 12px, `rgba(255,255,255,0.8)`, hover to full white. No underlines ever.
- Behavior: fixed/sticky, content scrolls beneath through the blur.
- Contents: brand mark left, 5–8 text links, search + one action (bag / "Try it") right.

### 7.2 Local nav (product bar, optional per page)

- Height ~52px, sits directly under globalnav, same blur treatment in light gray.
- Left: product name, 21px, weight 600. Right: section links 12px + one small pill CTA.

### 7.3 Ribbon (announcement bar)

- Optional thin bar above nav: 40–44px, dark, 12px centered text with a chevron link ("Get the latest →"). Use sparingly — launches only.

### 7.4 Footer (the "mega footer")

- Background: `#f5f5f7`.
- Entirely 12px text in `#6e6e73`, hairline `#d2d2d7` rules between link columns.
- Top: a footnotes block (`text-tertiary`) with numbered disclaimers.
- Below: 4–6 columns of links, then a legal row.
- This is an Apple signature — a generous, honest, low-contrast information dump after all the drama.

---

## 8. Components

### 8.1 Hero

- Full viewport (or ~624–780px) section; text block centered at top 15–25%, imagery filling lower portion.
- Structure: eyebrow (optional) → `display-hero` headline (2 lines max) → subhead 21px → two CTAs.
- CTA pattern — always two, this exact visual language:
  - Primary: **pill button**, filled `#0071e3`, white 17px text, ~22px vertical padding.
  - Secondary: **chevron link**, `Learn more ›` in `link` blue, no underline, chevron glyph (›), hover underlines.
- Background: white, `#f5f5f7`, or black + product photography. NEVER a busy gradient.

### 8.2 Tiles (the 2-up grid)

- Apple's homepage lower half: a grid of square-ish tiles, 2 per row desktop, 1 stacked mobile, 12px gutters.
- Each tile: image background, headline ~40px + subhead 19–21px + chevron links, all text top-aligned center.
- Tiles alternate light/dark to keep rhythm.

### 8.3 Feature cards (editorial section)

- White 18px-radius cards on `#f5f5f7`, or inverse.
- Interior padding 40–60px; headline `display-3`; image bottom-anchored.
- No shadow at rest. On hover: at most a subtle scale or a `2px 4px 12px rgba(0,0,0,.08)` lift — and often nothing at all.

### 8.4 Stats / numbers band (for Orchestra's "the numbers" section)

- Black section, huge semibold numerals (48–64px), 17px `text-secondary` labels beneath.
- 3 max per row. White space does the grouping; no card containers.

### 8.5 Spec/definition lists (docs-feel sections)

- Two-column definition rows separated by 1px hairlines. Term in 17px 600, value in 17px 400 secondary color. This is how Apple does tech specs — perfect for Orchestra's capabilities.

### 8.6 Inline dispatch/CTA band

- A single centered pill input or button on a quiet background, 17px, hairline border, `#0071e3` focus ring. One field, one button, nothing else on the row.

---

## 9. Backgrounds & Imagery

1. **Backgrounds are photographers' work, not CSS's.** Flat neutral fills carry text; imagery is real product-quality renders/photography, center-composed on the neutral field.
2. Full-bleed hero imagery may extend behind the translucent nav (the blur legibility layer exists exactly for this).
3. The one allowed CSS "texture": a photographic gradient where an image fades into the section background — implemented as part of the image asset, not a CSS gradient overlay.
4. Noise, glassmorphism panels, mesh gradients, and neumorphic shadows are all banned — none exist in Apple's marketing language.
5. For Orchestra with no photography yet: use large, precise monospaced/SVF-rendered product UI screenshots as the "product," floated on the neutral canvas with generous margins. A beautifully framed real screenshot beats any illustration.

---

## 10. Motion

### 10.1 Physics & curves

- Signature easing (measured from apple.com): `cubic-bezier(0.28, 0.11, 0.32, 1)` — fast attack, long soft settle.
- Durations: 400–800ms for entrances; 200ms for hover micro-states.
- Only `transform` and `opacity` animate. Never animate `width`, `height`, layout properties.

### 10.2 Vocabulary (sparse — choose deliberately)

| Motion | Where |
|---|---|
| Fade + 16–24px rise on scroll into view | Section headlines, cards (stagger 60–100ms) |
| Sticky pinned sections with scrub-driven image swap/scale | Product story sections ("as you scroll, the story advances") |
| Subtle parallax on hero imagery (≤ 8% travel) | Heroes only |
| Button hover: background shift `#0071e3`→`#0077ed`, 200ms | All CTAs |
| Link hover: underline draw | Text links |

### 10.3 Hard rules

- **`prefers-reduced-motion`: everything becomes an instant crossfade.** Apple ships this; we do too.
- Nothing loops. Nothing auto-plays on a timer. Nothing animates above the fold on load except ONE hero fade-in (600ms, once).
- Scroll-jacking (hijacked wheel/touch) is banned. Apple pins sections but never steals the scroll wheel.
- 60fps or don't ship it. Motion jank breaks the illusion more than no motion does.

---

## 11. Accessibility & Performance

- Contrast: `#1d1d1f` on `#fbfbfd` ≈ 15.9:1; `#6e6e73` on `#f5f5f7` ≈ 4.6:1 (AA pass at 12px+ only — keep secondary text ≥12px); `#f5f5f7` on `#000` ≈ 17.4:1. Maintain these ratios exactly.
- Focus: visible `#0071e3` 2px outline, never removed.
- All imagery gets real `alt` text or `alt=""` for pure decoration; hero headlines are real text, never baked into images.
- Touch targets ≥ 44px (matches the nav height for a reason).
- Semantic HTML throughout (`nav`, `main`, `section` with `aria-label`, `footer`).
- Performance budget: hero content visible < 1.5s on 4G; JS for scroll effects is progressive enhancement — page must read perfectly with JS disabled (Apple's pages largely do).

---

## 12. Token Map (ready for implementation)

```css
/* Reference tokens — the future build must derive from these verbatim */
:root {
  /* surfaces */
  --surface-canvas: #fbfbfd;
  --surface-raised: #f5f5f7;
  --surface-inverse: #000000;
  /* text */
  --text-primary: #1d1d1f;
  --text-secondary: #6e6e73;
  --text-tertiary: #86868b;
  --text-on-inverse: #f5f5f7;
  /* interactive */
  --accent: #0071e3;
  --accent-hover: #0077ed;
  --link: #0066cc;
  --link-inverse: #2997ff;
  /* structure */
  --hairline: #d2d2d7;
  --hairline-inverse: #424245;
  /* status (data only, from iOS system palette) */
  --status-good: #34c759;
  --status-warn: #ff9f0a;
  --status-bad: #ff453a;
  /* type stacks */
  --font-display: "SF Pro Display","SF Pro Icons","Helvetica Neue","Helvetica","Arial",sans-serif;
  --font-text: "SF Pro Text","SF Pro Icons","Helvetica Neue","Helvetica","Arial",sans-serif;
  --font-mono: "SF Mono","SFMono-Regular",ui-monospace,Menlo,monospace;
  /* motion */
  --ease-apple: cubic-bezier(0.28, 0.11, 0.32, 1);
  --dur-entrance: 600ms;
  --dur-hover: 200ms;
  /* structure */
  --radius-card: 18px;
  --radius-pill: 980px;
  --nav-height: 44px;
  --measure-prose: 680px;
  --container-editorial: 980px;
  --container-wide: 1400px;
}
```

---

## 13. Mapping onto Orchestra's surfaces

| Surface | Apple-language translation |
|---|---|
| `/` landing | apple.com homepage pattern: hero (one claim + dispatch CTA) → 2-up tile grid (the loop: plan → execute → review → learn) → black stats band (runs, cost, escalations) → spec-style capability list → mega footer |
| `/explorer` + task detail | Product-page discipline: local nav ("Explorer" + links), spec-list span details, hairline dividers, blue only on interactive trace nodes |
| `/dashboard` | White canvas, huge semibold numerals, hairline rules. Charts in neutral grays with single blue data accent and system status hues for health |
| `/approvals/ui` | Card-on-gray pattern; decision buttons use the exact pill vocabulary — approve = `#0071e3` fill, reject = hairline outline |
| `/memory/ui` | Document/editorial pattern: 680px measure, spec lists, footer-style low-contrast metadata |

The current "Signal Console" (dark, ember accent, Space Grotesk/JetBrains Mono) map: ember → `#0071e3`; Space Grotesk → SF Pro Display/Text; JetBrains Mono → SF Mono; OKLCH tokens → the hex tokens above. Data-dense panels keep their density — Apple language changes chrome and canvas, not information.

---

## 14. Anti-patterns (immediate failure)

- Any gradient behind text, glassmorphism cards, or decorative blobs
- Boxed card-in-card containers (Apple uses ONE surface level at a time)
- More than one accent hue in chrome
- Inter/Roboto/Poppins or any non-SF sans
- Persistent shadows on flat surfaces; animated loops; scroll-jacking
- Decorative emojis as icons (use SF Symbols-style stroke glyphs)
- Centered prose paragraphs (center heroes only; paragraphs left-align)
- Underlined links by default (Apple links are bare blue; underline on hover only)

---

## 15. Operator Checklist (verify before shipping the build)

- [ ] Aesthetic direction stated: *Cupertino Precision Minimalism* (DFII 13)
- [ ] SF Pro Display ≥20px / SF Pro Text <20px / SF Mono for data, correct fallback stack
- [ ] Exactly the tokens in §12 — no invented colors
- [ ] ~90/8/2 neutral/imagery/blue ratio held per page
- [ ] 44px blurred translucent nav; 12px nav links, no underlines
- [ ] Sections: 100px+ padding, one idea each, ≤2 consecutive dark sections
- [ ] Dual CTA pattern (pill + `Learn more ›`) on every hero
- [ ] Motion: transform/opacity only, `--ease-apple`, reduced-motion fallback
- [ ] Mega footer at 12px with hairlines and footnotes
- [ ] AA contrast maintained; 44px touch targets; focus rings intact

---

## 16. Memorability anchor

> **This avoids generic AI/SaaS UI by** letting typography and whitespace carry the entire hierarchy with zero decorative chrome, **instead of** stacking gradients, glass cards, and purple-tinted components around a cramped grid.

The thing users remember 24h later: the silence of the page on load — one huge statement in SF Pro on a field of light gray, and a single blue pill.
