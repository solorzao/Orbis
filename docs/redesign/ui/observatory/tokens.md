# Observatory: design tokens

> A warm, cinematic night-and-day observatory: a large off-centre globe inside a fine astrolabe ring, a narrative logbook beside it, and connections drawn as constellations.

Observatory is the second answer to "sci-fi mixed with soft, elegant UI", aimed at the luxury end: fewer, finer lines, more type, more darkness. The screen is composed like a film frame: a large globe sits off-centre to the right inside a hairline astrolabe ring, and a **logbook** runs down the left, one continuous column instead of separate panels. The returning-visitor note, the selected thread and the co-pilot conversation are written into it as entries. Champagne hairlines draw the instruments and brand cyan marks interaction. The memorable device is the **constellation**: the investigation board and the entity tracker draw their links as star charts, so "making connections" looks like naming stars. It ships Night and Day themes.

Machine-readable twin: [`tokens.json`](./tokens.json) (W3C Design Tokens format: `$value`, `$type`, `$description`, `{alias}` references). Mockup: [`mockup.html`](./mockup.html). Its `:root` block is generated from the same source, so the three never drift.

**Modes:** dark (default) and light. `$value` is dark; the light value lives in `$extensions["co.orbisapp"].modes.light`. CSS switches with `[data-theme="light"]` on `<html>`, same as the current app.

## Principles

1. One column of reading, one globe. No grid of panels: the logbook is a single scroll and only one floating card appears at a time over the globe.
2. Hairline instruments: the astrolabe ring, the time horizon and dividers are 1px champagne lines at low opacity. Nothing has a heavy border.
3. Type carries the luxury: Space Grotesk 300 for large titles and place names, 400 for reading, never bold. Mono numbers at 300.
4. Cyan is the only interactive colour. Champagne is for instruments and the active thread; it is never used for a button.
5. Calm motion: the globe drifts a few degrees, the active thread's arcs flow slowly, the ring does not move. Reduced motion stops all of it.
6. Night and Day share every role name, so components never branch on theme.

## Brand lockup (frozen)

Shared by all three directions and copied from `frontend/src/app/page.tsx`. Treat it as an asset, not a style.

| Part | Spec |
|---|---|
| Logo | `/Orbis_logo_50_resize.png`, 40px (28px mobile), `drop-shadow(0 0 12px rgba(0,212,255,.5))` |
| Wordmark | "Orbis", Orbitron 700, 18px/28px (14px/20px mobile), uppercase, tracking 0.2em, `text-shadow: 0 0 30px rgba(0,212,255,.4)`, colour #c8e6f8 dark / #1e293b light |
| Motto | "Every Story, Everywhere", system-ui 500, 9px, uppercase, tracking 0.3em, colour #3a7090 dark / #94a3b8 light, hidden below 640px |
| Layout | Logo then a text block, 12px gap (8px mobile), pinned top-left at 20px/24px (12px mobile) |

## Colour roles

### Sky

| Token | CSS var | Dark | Light | Use |
|---|---|---|---|---|
| `color.bg.page` | `--bg-page` | `#0e0d12` | `#eef0f4` | Night: warm ink. Day: cool porcelain (deliberately not cream). |
| `color.bg.glow` | `--bg-glow` | `rgba(233, 205, 160, 0.09)` | `rgba(255, 255, 255, 0.85)` | Soft light behind the globe. |
| `color.bg.inset` | `--bg-inset` | `rgba(255, 255, 255, 0.04)` | `rgba(20, 22, 32, 0.04)` | Inputs, wells. |

### Surfaces

| Token | CSS var | Dark | Light | Use |
|---|---|---|---|---|
| `color.surface.log` | `--surface-log` | `rgba(14, 13, 18, 0.94)` | `rgba(238, 240, 244, 0.95)` | Logbook scrim (solid edge on the left, fading to the globe). |
| `color.surface.card` | `--surface-card` | `rgba(28, 26, 34, 0.78)` | `rgba(255, 255, 255, 0.82)` | Floating card over the globe (with blur.card). |
| `color.surface.raised` | `--surface-raised` | `rgba(255, 255, 255, 0.045)` | `rgba(20, 22, 32, 0.045)` | Rows and chips. |
| `color.surface.hover` | `--surface-hover` | `rgba(255, 255, 255, 0.07)` | `rgba(20, 22, 32, 0.07)` | Hover wash. |
| `color.surface.sheet` | `--surface-sheet` | `rgba(12, 11, 16, 0.94)` | `rgba(244, 245, 248, 0.96)` | Constellation board. |

### Hairlines

| Token | CSS var | Dark | Light | Use |
|---|---|---|---|---|
| `color.border.hairline` | `--border-hairline` | `rgba(233, 216, 180, 0.14)` | `rgba(60, 52, 40, 0.14)` | Dividers and card outlines. |
| `color.border.default` | `--border-default` | `rgba(233, 216, 180, 0.24)` | `rgba(60, 52, 40, 0.24)` | Controls. |
| `color.border.strong` | `--border-strong` | `rgba(233, 216, 180, 0.48)` | `rgba(60, 52, 40, 0.55)` | Axes, focused controls. |
| `color.border.focus` | `--border-focus` | `#6fe0ff` | `#006d92` | Focus ring. |

### Text

| Token | CSS var | Dark | Light | Use |
|---|---|---|---|---|
| `color.text.primary` | `--text-primary` | `#f3efe8` | `#1b1a20` | Titles and values. |
| `color.text.secondary` | `--text-secondary` | `#cdc6ba` | `#45424d` | Reading text. |
| `color.text.muted` | `--text-muted` | `#a0998d` | `#625e6a` | Labels, timestamps. |
| `color.text.inverse` | `--text-inverse` | `#0e0d12` | `#ffffff` | Text on cyan. |

### Accent (brand cyan) and champagne

| Token | CSS var | Dark | Light | Use |
|---|---|---|---|---|
| `color.accent.primary` | `--accent-primary` | `#00d4ff` | `#006d92` | Brand cyan: every interactive element. |
| `color.accent.strong` | `--accent-strong` | `#6fe0ff` | `#00546f` | Hover, cyan text. |
| `color.accent.soft` | `--accent-soft` | `rgba(0, 212, 255, 0.12)` | `rgba(0, 109, 146, 0.10)` | Active fills. |
| `color.accent.on` | `--accent-on` | `#06131a` | `#ffffff` | Foreground on cyan. |
| `color.accent.champagne` | `--accent-champagne` | `#e6cfa3` | `#7d5f27` | Instruments, the active thread, constellation stars. Never a button. |
| `color.accent.champagneSoft` | `--accent-champagne-soft` | `rgba(230, 207, 163, 0.14)` | `rgba(138, 106, 47, 0.12)` | Champagne wash (time window band). |

### Status signals

| Token | CSS var | Dark | Light | Use |
|---|---|---|---|---|
| `color.signal.live` | `--signal-live` | `#8fdcb5` | `#1f7a52` | Live indicator. |
| `color.signal.warning` | `--signal-warning` | `#f0b97a` | `#94570f` | Surges, stale data. |
| `color.signal.danger` | `--signal-danger` | `#f08f8f` | `#b3352f` | Offline, errors. |

### Globe

| Token | CSS var | Dark | Light | Use |
|---|---|---|---|---|
| `color.globe.tint` | `--globe-tint` | `#ffffff` | `#ffffff` | Material colour while the texture loads; three-globe then shows the texture untinted (night lights in Night, blue marble in Day). |
| `color.globe.emissive` | `--globe-emissive` | `#140f08` | `#000000` | Warm self-light in Night. |
| `color.globe.atmosphere` | `--globe-atmosphere` | `#7fcfff` | `#9cc9e6` | Cool rim against the warm city lights. |

### Connection arcs

| Token | CSS var | Dark | Light | Use |
|---|---|---|---|---|
| `color.arc.coverage` | `--arc-coverage` | `rgba(233, 216, 180, 0.26)` | `rgba(60, 52, 40, 0.30)` | Co-coverage link. Width encodes story count. |
| `color.arc.highlight` | `--arc-highlight` | `#6fe0ff` | `#006d92` | Inspected link. |
| `color.arc.muted` | `--arc-muted` | `rgba(233, 216, 180, 0.08)` | `rgba(60, 52, 40, 0.08)` | Filtered-out links. |
| `color.arc.relationCooperation` | `--arc-relation-cooperation` | `#8fb8ff` | `#2f5fb3` | Actor relation, cooperation (later phase). |
| `color.arc.relationConflict` | `--arc-relation-conflict` | `#f29a8f` | `#b3412f` | Actor relation, conflict (later phase). |

### Instruments

| Token | CSS var | Dark | Light | Use |
|---|---|---|---|---|
| `color.chart.ring` | `--chart-ring` | `rgba(233, 216, 180, 0.22)` | `rgba(60, 52, 40, 0.24)` | Astrolabe ring and graduations. |
| `color.chart.tick` | `--chart-tick` | `rgba(233, 216, 180, 0.40)` | `rgba(60, 52, 40, 0.45)` | Major graduations, horizon ticks. |
| `color.chart.star` | `--chart-star` | `#f6e7c8` | `#7a5a22` | Constellation stars (board pins, entity nodes). |
| `color.chart.line` | `--chart-line` | `rgba(246, 231, 200, 0.45)` | `rgba(122, 90, 34, 0.45)` | Constellation lines. |

## Data-viz palettes

### Sentiment (diverging, -1 to +1)

Clay rose to sage-teal through a warm grey, quieter than the other directions so it sits inside a warm palette. The ends differ in lightness; every value prints its signed score.

| Token | CSS var | Dark | Light | Use |
|---|---|---|---|---|
| `dataviz.sentiment.n3` | `--sentiment-n3` | `#ec8c84` | `#b0443a` | Strongly negative (<= -0.6). |
| `dataviz.sentiment.n2` | `--sentiment-n2` | `#e2a99c` | `#c06a5c` | Negative. |
| `dataviz.sentiment.n1` | `--sentiment-n1` | `#cdb7ad` | `#a68c83` | Slightly negative. |
| `dataviz.sentiment.neutral` | `--sentiment-neutral` | `#aaa59c` | `#86817a` | Neutral. |
| `dataviz.sentiment.p1` | `--sentiment-p1` | `#b2cfc4` | `#7aa395` | Slightly positive. |
| `dataviz.sentiment.p2` | `--sentiment-p2` | `#90d3bd` | `#3d8f74` | Positive. |
| `dataviz.sentiment.p3` | `--sentiment-p3` | `#6ccfae` | `#1d7457` | Strongly positive (>= 0.6). |

Binning: `n3` <= -0.6 < `n2` <= -0.3 < `n1` <= -0.1 < `neutral` < 0.1 <= `p1` < 0.3 <= `p2` < 0.6 <= `p3`. Always print the signed score (e.g. `-0.42`) next to the colour; colour is never the only channel.

### Topics (categorical)

Muted, slightly warm topic hues with Night and Day variants. Technology is a sky blue (not cyan); Economy is a soft gold that stays distinct from champagne by saturation.

| Token | CSS var | Dark | Light | Use |
|---|---|---|---|---|
| `dataviz.topic.all` | `--topic-all` | `#cdc6ba` | `#45424d` | No topic filter. |
| `dataviz.topic.politics` | `--topic-politics` | `#b3a3f0` | `#5f4cc4` | Politics. |
| `dataviz.topic.conflict` | `--topic-conflict` | `#ef8f8f` | `#b8382f` | Conflict. |
| `dataviz.topic.technology` | `--topic-technology` | `#8cbcf0` | `#2c66b8` | Technology. |
| `dataviz.topic.climate` | `--topic-climate` | `#86d4ad` | `#23794f` | Climate. |
| `dataviz.topic.economy` | `--topic-economy` | `#f2c66f` | `#8a6400` | Economy. |
| `dataviz.topic.health` | `--topic-health` | `#eea3c6` | `#a83d74` | Health. |

## Typography

Editorial and light: large 300-weight titles, a 15px reading size with 24px leading, and mono numbers at 300.

| Font role | Stack | Use |
|---|---|---|
| `font.family.brand` (`--font-brand`) | Orbitron, sans-serif | Wordmark only. |
| `font.family.heading` (`--font-heading`) | Space Grotesk, system-ui, sans-serif | Titles at 300, labels at 400. |
| `font.family.body` (`--font-body`) | Space Grotesk, system-ui, sans-serif | Reading text at 400. |
| `font.family.mono` (`--font-mono`) | JetBrains Mono, ui-monospace, monospace | Numbers only, at 300 to 400. |

| Style | Family | Size / line | Weight | Tracking | Use |
|---|---|---|---|---|---|
| `typography.display` | Space Grotesk | 30/36 | 300 | -0.015em | Logbook entry titles, place name in the hover card. |
| `typography.title` | Space Grotesk | 20/28 | 300 | -0.01em | Card titles. |
| `typography.heading` | Space Grotesk | 15/22 | 400 | 0 | Section heads, headlines. |
| `typography.body` | Space Grotesk | 15/24 | 400 | 0 | Reading text. |
| `typography.bodySm` | Space Grotesk | 13/20 | 400 | 0 | Secondary text. |
| `typography.label` | Space Grotesk | 12/16 | 400 | 0.02em | Labels (sentence case). |
| `typography.dataXl` | JetBrains Mono | 32/36 | 300 | 0 | Hero numbers in the logbook. Uses `"tnum" 1`. |
| `typography.data` | JetBrains Mono | 12/16 | 400 | 0 | Scores, counts, times. Uses `"tnum" 1`. |
| `typography.dataSm` | JetBrains Mono | 11/14 | 300 | 0.02em | Graduations, coordinates. Uses `"tnum" 1`. |

CSS: each style is a `font` shorthand, e.g. `font: var(--type-display);`, plus `letter-spacing: var(--tracking-*)` where tracking is non-zero.

## Space, radii, borders

Generous: 32px between logbook entries, 24px inside cards, 48px screen margins on desktop.

| Space | `0` | `1` | `2` | `3` | `4` | `5` | `6` | `7` | `8` |
|---|---|---|---|---|---|---|---|---|---|
| px | 0 | 4 | 8 | 12 | 16 | 24 | 32 | 48 | 64 |

Rounded but restrained: 18px cards, pills for controls, 8px for images.

| Radius | Value | Use |
|---|---|---|
| `radius.sm` | 8px | Images. |
| `radius.md` | 14px | Rows, chips inside cards. |
| `radius.lg` | 18px | Floating cards, the board sheet. |
| `radius.pill` | 999px | Buttons, chips, toggles. |

| Border width | Value | Use |
|---|---|---|
| `borderWidth.hairline` | 1px | Everything. |
| `borderWidth.focus` | 2px | Focus ring only. |

| Blur | Value | Use |
|---|---|---|
| `blur.card` | 20px | Floating card over the globe. 0 in low-power mode. |

## Elevation and glow

Depth comes from light falling off, not from borders: one wide shadow under floating cards, and a warm glow behind the globe.

| Token | Dark | Light | Use |
|---|---|---|---|
| `elevation.card` | `0px 28px 70px -16px rgba(0, 0, 0, 0.6)` | `0px 24px 60px -18px rgba(30, 30, 50, 0.22)` | Floating cards. |
| `elevation.star` | `0px 0px 12px 0px rgba(246, 231, 200, 0.55)` | `0px 0px 0px 0px rgba(0, 0, 0, 0)` | Constellation stars (Night only). |

## Motion

Slow and continuous where ambient, quick where responsive. Reduced motion stops drift and arc flow, and turns fly-to into a cut.

| Token | CSS var | Value | Use |
|---|---|---|---|
| `motion.duration.fast` | `--dur-fast` | `160ms` | Hover. |
| `motion.duration.base` | `--dur-base` | `300ms` | Card and entry changes. |
| `motion.duration.slow` | `--dur-slow` | `520ms` | Logbook entry expand. |
| `motion.duration.flyTo` | `--dur-fly-to` | `1800ms` | Camera move. |
| `motion.duration.arcFlow` | `--dur-arc-flow` | `7000ms` | Active thread arc flow. |
| `motion.duration.drift` | `--dur-drift` | `48000ms` | Globe drift period. |
| `motion.easing.out` | `--ease-out` | `cubic-bezier(0.16, 1, 0.3, 1)` | Entrances (ease-out-expo). |
| `motion.easing.inOut` | `--ease-in-out` | `cubic-bezier(0.65, 0, 0.35, 1)` | Camera. |
| `motion.easing.standard` | `--ease-standard` | `cubic-bezier(0.2, 0, 0, 1)` | Small state changes. |

## Component patterns

### Logbook

The left column: a single scroll of entries (welcome back, thread, co-pilot, inspections) on a scrim that fades into the scene. Entries are separated by space and a short champagne hairline, never boxed. New entries (an opened link, a tracked entity) are added at the top.

| Property | Token / value |
|---|---|
| `component.logbook.background` | `{color.surface.log}` |
| `component.logbook.width` | `440px` |
| `component.logbook.entryGap` | `{space.6}` |
| `component.logbook.divider` | `{color.border.hairline}` |
| `component.logbook.title` | `{typography.display}` |
| `component.logbook.body` | `{typography.body}` |

### Floating card

The only boxed element: a rounded translucent card over the globe for the hover preview and the inspector. 1px hairline, wide soft shadow.

| Property | Token / value |
|---|---|
| `component.floatCard.background` | `{color.surface.card}` |
| `component.floatCard.border` | `{color.border.hairline}` |
| `component.floatCard.radius` | `{radius.lg}` |
| `component.floatCard.blur` | `{blur.card}` |
| `component.floatCard.shadow` | `{elevation.card}` |
| `component.floatCard.padding` | `{space.5}` |

### Pill control

Text-first pills: transparent with a hairline; active ones get `accent.soft` and cyan text.

| Property | Token / value |
|---|---|
| `component.pill.height` | `30px` |
| `component.pill.radius` | `{radius.pill}` |
| `component.pill.border` | `{color.border.default}` |
| `component.pill.activeFill` | `{color.accent.soft}` |
| `component.pill.activeText` | `{color.accent.strong}` |
| `component.pill.label` | `{typography.label}` |

### Astrolabe ring

A hairline circle at 1.06R with minor graduations every 2 degrees, majors every 10 and coordinate labels every 30, plus a second partial ring at 1.14R carrying the topic legend. Static.

| Property | Token / value |
|---|---|
| `component.astrolabe.ring` | `{color.chart.ring}` |
| `component.astrolabe.tick` | `{color.chart.tick}` |
| `component.astrolabe.label` | `{typography.dataSm}` |
| `component.astrolabe.radiusFactor` | `1.06` |

### Time horizon

A long hairline under the globe with hourly ticks whose height is story volume, a champagne window band, a cyan playhead, a last-visit mark and a round replay button at its left end.

| Property | Token / value |
|---|---|
| `component.horizon.line` | `{color.chart.tick}` |
| `component.horizon.window` | `{color.accent.champagneSoft}` |
| `component.horizon.playhead` | `{color.accent.primary}` |
| `component.horizon.height` | `56px` |

### Constellation

Board pins and co-mentioned entities drawn as stars (size by weight) joined by hairlines; labels sit beside stars in `typography.label`. User-drawn links are dashed, automatic ones solid.

| Property | Token / value |
|---|---|
| `component.constellation.star` | `{color.chart.star}` |
| `component.constellation.line` | `{color.chart.line}` |
| `component.constellation.glow` | `{elevation.star}` |
| `component.constellation.label` | `{typography.label}` |

### Connection arc

Active thread: champagne fading to cyan, stroke 0.5, slow flow. Co-coverage: faint champagne. Inspected link: `arc.highlight` with a text label at 70% of its length.

| Property | Token / value |
|---|---|
| `component.connection.active` | `{color.accent.champagne}` |
| `component.connection.coverage` | `{color.arc.coverage}` |
| `component.connection.highlight` | `{color.arc.highlight}` |
| `component.connection.flow` | `{motion.duration.arcFlow}` |

### Co-pilot entry

The co-pilot writes into the logbook: your question in secondary text, the answer in reading text with small numbered citations, then a row of action pills. The input is pinned to the bottom of the logbook.

| Property | Token / value |
|---|---|
| `component.console.prose` | `{typography.body}` |
| `component.console.citation` | `{color.accent.strong}` |
| `component.console.actionBorder` | `{color.border.default}` |
| `component.console.inputBackground` | `{color.bg.inset}` |

## Accessibility check (computed)

WCAG 2.x contrast ratios, generated from the token values (translucent surfaces composited over `bg.page`). Target: 4.5 for text, 3.0 for large text and non-text UI.

| Mode | Surface | Foreground | Ratio | Target | Result |
|---|---|---|---|---|---|
| dark | bg.page | text.primary | 16.89 | 4.5 | pass |
| dark | bg.page | text.secondary | 11.41 | 4.5 | pass |
| dark | bg.page | text.muted | 6.85 | 4.5 | pass |
| dark | bg.page | accent.strong (as text) | 12.70 | 4.5 | pass |
| dark | bg.page | accent.champagne (as text) | 12.74 | 4.5 | pass |
| dark | bg.page | border.strong (UI) | 3.87 | 3 | pass |
| dark | bg.page | sentiment.n3 (mark) | 7.97 | 3 | pass |
| dark | logbook | text.primary | 16.89 | 4.5 | pass |
| dark | logbook | text.secondary | 11.41 | 4.5 | pass |
| dark | logbook | text.muted | 6.85 | 4.5 | pass |
| dark | logbook | accent.strong (as text) | 12.70 | 4.5 | pass |
| dark | logbook | accent.champagne (as text) | 12.74 | 4.5 | pass |
| dark | logbook | border.strong (UI) | 3.87 | 3 | pass |
| dark | logbook | sentiment.n3 (mark) | 7.97 | 3 | pass |
| dark | floating card | text.primary | 15.47 | 4.5 | pass |
| dark | floating card | text.secondary | 10.46 | 4.5 | pass |
| dark | floating card | text.muted | 6.28 | 4.5 | pass |
| dark | floating card | accent.strong (as text) | 11.64 | 4.5 | pass |
| dark | floating card | accent.champagne (as text) | 11.67 | 4.5 | pass |
| dark | floating card | border.strong (UI) | 3.84 | 3 | pass |
| dark | floating card | sentiment.n3 (mark) | 7.31 | 3 | pass |
| light | bg.page | text.primary | 15.15 | 4.5 | pass |
| light | bg.page | text.secondary | 8.60 | 4.5 | pass |
| light | bg.page | text.muted | 5.53 | 4.5 | pass |
| light | bg.page | accent.strong (as text) | 7.37 | 4.5 | pass |
| light | bg.page | accent.champagne (as text) | 5.20 | 4.5 | pass |
| light | bg.page | border.strong (UI) | 3.07 | 3 | pass |
| light | bg.page | sentiment.n3 (mark) | 4.93 | 3 | pass |
| light | logbook | text.primary | 15.15 | 4.5 | pass |
| light | logbook | text.secondary | 8.60 | 4.5 | pass |
| light | logbook | text.muted | 5.53 | 4.5 | pass |
| light | logbook | accent.strong (as text) | 7.37 | 4.5 | pass |
| light | logbook | accent.champagne (as text) | 5.20 | 4.5 | pass |
| light | logbook | border.strong (UI) | 3.07 | 3 | pass |
| light | logbook | sentiment.n3 (mark) | 4.93 | 3 | pass |
| light | floating card | text.primary | 16.88 | 4.5 | pass |
| light | floating card | text.secondary | 9.59 | 4.5 | pass |
| light | floating card | text.muted | 6.16 | 4.5 | pass |
| light | floating card | accent.strong (as text) | 8.21 | 4.5 | pass |
| light | floating card | accent.champagne (as text) | 5.80 | 4.5 | pass |
| light | floating card | border.strong (UI) | 3.18 | 3 | pass |
| light | floating card | sentiment.n3 (mark) | 5.49 | 3 | pass |

## Mobile adaptation

- The globe moves to the top half and is centred; the astrolabe keeps its ring but drops labels.
- The logbook becomes the page: it scrolls under the globe, with the co-pilot input pinned to the bottom of the screen.
- The hover card becomes a tap card inside the logbook ("You tapped Lagos"), so nothing floats over the globe on small screens.
- The time horizon becomes a full-width strip between the globe and the logbook.

## Do and don't

- Do keep one floating card at a time.
- Do write new information into the logbook rather than opening another panel.
- Don't use champagne for controls or cyan for instruments.
- Don't use weights above 400 except the frozen wordmark.
