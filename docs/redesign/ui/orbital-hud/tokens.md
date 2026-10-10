# Orbital HUD: design tokens

> The globe is the cockpit window: a full-bleed holographic HUD with an instrument ring for topics and time, lock-on previews and pulsing connection arcs.

**Status: built before the owner's feedback.** It is the most cinematic of the four and the hardest-edged; read it as the "more sci-fi" end of the range rather than a candidate for the softer brief.

Orbital HUD is the closest to the app's current personality, pushed to its conclusion. The globe fills the screen and everything else is instrumentation drawn on the glass in front of it. Its one memorable device is the **instrument ring**: a calibrated ring around the globe whose top arc is the topic selector and whose bottom arc is a 7-day radial histogram you scrub to travel in time. Glow is a resource with a budget: only live, selected or locked-on elements emit light.

Machine-readable twin: [`tokens.json`](./tokens.json) (W3C Design Tokens format: `$value`, `$type`, `$description`, `{alias}` references). Mockup: [`mockup.html`](./mockup.html). Its `:root` block is generated from the same source, so the three never drift.

**Modes:** dark only. The HUD is drawn in light on darkness: glows, additive arcs and translucent glass have no sensible light equivalent. If a light theme stays a requirement, ship Signal Desk's light mode as the "daylight" fallback rather than inverting this one.

## Principles

1. One hero: the globe and its ring. Panels are thin glass at the edges and never cover the ring.
2. Glow budget: at most one glowing element per region of the screen. Glow means live, selected or locked on.
3. Corner brackets are the HUD's one motif: glass panels, readouts and the lock-on reticle all use the same L-shaped brackets. Pills only for chips and buttons.
4. One orchestrated moment: the ring draws in and the reticle locks on at load. After that, motion only marks change (new data, a lock-on, a fly-to).
5. Arcs move to show direction of influence (source story to follow-up). They stop under prefers-reduced-motion.
6. Text stays solid and legible: glow is applied to strokes and dots, never behind body copy.

## Brand lockup (frozen)

Shared by all three directions and copied from `frontend/src/app/page.tsx`. Treat it as an asset, not a style.

| Part | Spec |
|---|---|
| Logo | `/Orbis_logo_50_resize.png`, 40px (28px mobile), `drop-shadow(0 0 12px rgba(0,212,255,.5))` |
| Wordmark | "Orbis", Orbitron 700, 18px/28px (14px/20px mobile), uppercase, tracking 0.2em, `text-shadow: 0 0 30px rgba(0,212,255,.4)`, colour #c8e6f8 dark / #1e293b light |
| Motto | "Every Story, Everywhere", system-ui 500, 9px, uppercase, tracking 0.3em, colour #3a7090 dark / #94a3b8 light, hidden below 640px |
| Layout | Logo then a text block, 12px gap (8px mobile), pinned top-left at 20px/24px (12px mobile) |

## Colour roles

### Background

| Token | CSS var | Value | Use |
|---|---|---|---|
| `color.bg.page` | `--bg-page` | `#01050a` | Deep space behind the globe. |
| `color.bg.inset` | `--bg-inset` | `rgba(0, 18, 30, 0.72)` | Inputs and chart wells inside glass. |

### Glass surfaces

| Token | CSS var | Value | Use |
|---|---|---|---|
| `color.surface.panel` | `--surface-panel` | `rgba(4, 20, 32, 0.66)` | Glass panel (with blur.panel). Solid fallback: #061520. |
| `color.surface.raised` | `--surface-raised` | `rgba(8, 32, 48, 0.72)` | Panel header band, hovered list item. |
| `color.surface.overlay` | `--surface-overlay` | `rgba(3, 18, 30, 0.84)` | Lock-on preview card. |
| `color.surface.hover` | `--surface-hover` | `rgba(0, 212, 255, 0.08)` | Hover wash. |
| `color.surface.selected` | `--surface-selected` | `rgba(0, 212, 255, 0.15)` | Selected wash. |

### Strokes

| Token | CSS var | Value | Use |
|---|---|---|---|
| `color.border.subtle` | `--border-subtle` | `rgba(0, 212, 255, 0.14)` | Internal dividers. |
| `color.border.default` | `--border-default` | `rgba(0, 212, 255, 0.30)` | Glass panel stroke. |
| `color.border.strong` | `--border-strong` | `rgba(127, 233, 255, 0.62)` | Corner brackets, active strokes. |
| `color.border.focus` | `--border-focus` | `#7fe9ff` | Keyboard focus ring. |

### Text

| Token | CSS var | Value | Use |
|---|---|---|---|
| `color.text.primary` | `--text-primary` | `#e2f8ff` | Headlines and values. |
| `color.text.secondary` | `--text-secondary` | `#9fd2e4` | Body copy. |
| `color.text.muted` | `--text-muted` | `#74acc2` | Captions, units, ring labels. |
| `color.text.inverse` | `--text-inverse` | `#00121a` | Text on solid cyan. |

### Accent (brand cyan)

| Token | CSS var | Value | Use |
|---|---|---|---|
| `color.accent.primary` | `--accent-primary` | `#00d4ff` | Brand cyan: selection, live strokes. |
| `color.accent.strong` | `--accent-strong` | `#7fe9ff` | Ice: hover, lock-on reticle. |
| `color.accent.soft` | `--accent-soft` | `rgba(0, 212, 255, 0.16)` | Active segment fill. |
| `color.accent.on` | `--accent-on` | `#00121a` | Foreground on solid accent. |

### Status signals

| Token | CSS var | Value | Use |
|---|---|---|---|
| `color.signal.live` | `--signal-live` | `#6ff7c4` | Live indicator. |
| `color.signal.warning` | `--signal-warning` | `#ffc04d` | Stale or partial data. |
| `color.signal.danger` | `--signal-danger` | `#ff5c70` | Offline, errors. |

### Globe

| Token | CSS var | Value | Use |
|---|---|---|---|
| `color.globe.tint` | `--globe-tint` | `#0a1a2e` | Material colour until the texture loads (three-globe then clears it, as in the current app); the glow comes from emissive. |
| `color.globe.emissive` | `--globe-emissive` | `#063040` | Material self-glow (emissiveIntensity 0.6). |
| `color.globe.atmosphere` | `--globe-atmosphere` | `#00d4ff` | Atmosphere (altitude 0.22). |

### Connection arcs

| Token | CSS var | Value | Use |
|---|---|---|---|
| `color.arc.coverage` | `--arc-coverage` | `rgba(159, 210, 228, 0.40)` | Co-coverage link, neutral; width encodes story count. |
| `color.arc.highlight` | `--arc-highlight` | `#7fe9ff` | Inspected link or selected thread. |
| `color.arc.muted` | `--arc-muted` | `rgba(127, 233, 255, 0.10)` | Filtered-out connections. |
| `color.arc.relationCooperation` | `--arc-relation-cooperation` | `#6aa8ff` | Actor relation, cooperation (later phase). |
| `color.arc.relationConflict` | `--arc-relation-conflict` | `#ff6b7d` | Actor relation, conflict (later phase). |

### HUD instrumentation

| Token | CSS var | Value | Use |
|---|---|---|---|
| `color.hud.ringTrack` | `--hud-ring-track` | `rgba(0, 212, 255, 0.20)` | Instrument ring track. |
| `color.hud.ringTick` | `--hud-ring-tick` | `rgba(127, 233, 255, 0.42)` | Degree ticks and histogram bars (unselected). |
| `color.hud.ringActive` | `--hud-ring-active` | `#00d4ff` | Selected time range and topic segment. |
| `color.hud.reticle` | `--hud-reticle` | `#7fe9ff` | Lock-on brackets and leader line. |
| `color.hud.scanline` | `--hud-scanline` | `rgba(0, 212, 255, 0.05)` | Static scanline texture on images and glass. |

## Data-viz palettes

### Sentiment (diverging, -1 to +1)

Flare (warm red) to aurora (mint) through a cool grey. Built to stay readable as luminous marks on black: the positive end is much lighter than the negative end, so the scale survives red-green colour blindness, and every value prints its signed score.

| Token | CSS var | Value | Use |
|---|---|---|---|
| `dataviz.sentiment.n3` | `--sentiment-n3` | `#ff5c70` | Strongly negative (<= -0.6). |
| `dataviz.sentiment.n2` | `--sentiment-n2` | `#ff8f80` | Negative. |
| `dataviz.sentiment.n1` | `--sentiment-n1` | `#e6b5ae` | Slightly negative. |
| `dataviz.sentiment.neutral` | `--sentiment-neutral` | `#8fb0bf` | Neutral. |
| `dataviz.sentiment.p1` | `--sentiment-p1` | `#a9e8d3` | Slightly positive. |
| `dataviz.sentiment.p2` | `--sentiment-p2` | `#5ff0c0` | Positive. |
| `dataviz.sentiment.p3` | `--sentiment-p3` | `#19f5a8` | Strongly positive (>= 0.6). |

Binning: `n3` <= -0.6 < `n2` <= -0.3 < `n1` <= -0.1 < `neutral` < 0.1 <= `p1` < 0.3 <= `p2` < 0.6 <= `p3`. Always print the signed score (e.g. `-0.42`) next to the colour; colour is never the only channel.

### Topics (categorical)

Luminous versions of the current topic hues, tuned to glow on black. Technology moves from cyan to azure so cyan stays the HUD's own voice.

| Token | CSS var | Value | Use |
|---|---|---|---|
| `dataviz.topic.all` | `--topic-all` | `#9fd2e4` | No topic filter. |
| `dataviz.topic.politics` | `--topic-politics` | `#b49aff` | Politics. |
| `dataviz.topic.conflict` | `--topic-conflict` | `#ff5c70` | Conflict. |
| `dataviz.topic.technology` | `--topic-technology` | `#5cb8ff` | Technology (was #06B6D4). |
| `dataviz.topic.climate` | `--topic-climate` | `#4ff0a8` | Climate. |
| `dataviz.topic.economy` | `--topic-economy` | `#ffc04d` | Economy. |
| `dataviz.topic.health` | `--topic-health` | `#ff7ad9` | Health. |

## Typography

Airier than the desk: 14px body, generous line height, and a light-weight mono for large readouts so numbers feel projected rather than printed.

| Font role | Stack | Use |
|---|---|---|
| `font.family.brand` (`--font-brand`) | Orbitron, sans-serif | Wordmark only. Never used for HUD readouts, so the brand stays distinct. |
| `font.family.heading` (`--font-heading`) | Space Grotesk, system-ui, sans-serif | Panel titles, headlines, ring labels. |
| `font.family.body` (`--font-body`) | Space Grotesk, system-ui, sans-serif | Prose. |
| `font.family.mono` (`--font-mono`) | JetBrains Mono, ui-monospace, monospace | Readouts, coordinates, scores, timestamps. |

| Style | Family | Size / line | Weight | Tracking | Use |
|---|---|---|---|---|---|
| `typography.title` | Space Grotesk | 18/24 | 600 | -0.01em | Lock-on preview headline. |
| `typography.heading` | Space Grotesk | 14/18 | 600 | 0.01em | Panel titles. |
| `typography.body` | Space Grotesk | 14/21 | 400 | 0 | Co-pilot answers, summaries. |
| `typography.bodySm` | Space Grotesk | 13/19 | 400 | 0 | List items, secondary prose. |
| `typography.label` | Space Grotesk | 12/16 | 500 | 0.02em | Ring labels, control labels. |
| `typography.readoutXl` | JetBrains Mono | 26/30 | 300 | 0 | UTC clock. Uses `"tnum" 1, "zero" 1`. |
| `typography.dataLg` | JetBrains Mono | 18/22 | 400 | 0 | Headline numbers in panels. Uses `"tnum" 1`. |
| `typography.data` | JetBrains Mono | 12/16 | 400 | 0 | Scores, counts, timestamps. Uses `"tnum" 1`. |
| `typography.dataSm` | JetBrains Mono | 11/14 | 400 | 0.04em | Ticks, coordinates, units. Uses `"tnum" 1`. |

CSS: each style is a `font` shorthand, e.g. `font: var(--type-title);`, plus `letter-spacing: var(--tracking-*)` where tracking is non-zero.

## Space, radii, borders

4px base. Glass panels breathe more than the desk: 16px padding, 12px between items.

| Space | `0` | `1` | `2` | `3` | `4` | `5` | `6` | `7` | `8` |
|---|---|---|---|---|---|---|---|---|---|
| px | 0 | 2 | 4 | 8 | 12 | 16 | 24 | 32 | 48 |

Glass panels are square-cornered and marked by corner brackets (`radius.bracket` is the bracket arm length, drawn with background gradients so no clip-path is needed). Chips and buttons are pills, so glass and controls are never confused.

| Radius | Value | Use |
|---|---|---|
| `radius.none` | 0px | Glass panels. |
| `radius.bracket` | 10px | Corner bracket arm length on panels, readouts and the reticle. |
| `radius.pill` | 999px | Chips, buttons, status dots. |

| Border width | Value | Use |
|---|---|---|
| `borderWidth.hairline` | 1px | Glass strokes, ticks. |
| `borderWidth.strong` | 2px | Corner brackets, active ring segment. |

| Blur | Value | Use |
|---|---|---|
| `blur.panel` | 14px | Glass panels. Dropped to 0 in low-power mode. |
| `blur.overlay` | 18px | Preview card. |

## Elevation and glow

No drop shadows: depth comes from light. Glows are cyan, short and reserved for state.

| Token | Value | Use |
|---|---|---|
| `elevation.glowSm` | `0px 0px 8px 0px rgba(0, 212, 255, 0.35)` | Live dot, active chip. |
| `elevation.glowMd` | `0px 0px 22px 0px rgba(0, 212, 255, 0.28)` | Locked-on preview card edge. |
| `elevation.innerEdge` | `inset 0px 1px 0px 0px rgba(127, 233, 255, 0.10)` | Top-edge highlight on glass. |

## Motion

Cinematic but bounded. One boot sequence (ring draw + lock-on), then motion only marks change. Under `prefers-reduced-motion: reduce`: no boot sequence, no arc dashes, no auto-rotate, fly-to becomes a cut. A low-power mode (auto-enabled when `navigator.hardwareConcurrency <= 4` or frame time > 24ms) also drops blur and dashes.

| Token | CSS var | Value | Use |
|---|---|---|---|
| `motion.duration.fast` | `--dur-fast` | `140ms` | Hover, chip toggle. |
| `motion.duration.base` | `--dur-base` | `220ms` | Panel content change. |
| `motion.duration.lockOn` | `--dur-lock-on` | `420ms` | Reticle brackets converge on a location. |
| `motion.duration.ringDraw` | `--dur-ring-draw` | `1100ms` | Ring draws in on first load (once). |
| `motion.duration.flyTo` | `--dur-fly-to` | `1400ms` | Camera move. |
| `motion.duration.arcDash` | `--dur-arc-dash` | `4000ms` | One dash cycle along a selected thread arc. |
| `motion.easing.standard` | `--ease-standard` | `cubic-bezier(0.2, 0, 0, 1)` | UI. |
| `motion.easing.emphasized` | `--ease-emphasized` | `cubic-bezier(0.16, 1, 0.3, 1)` | Lock-on, ring draw (fast out, long settle). |
| `motion.easing.camera` | `--ease-camera` | `cubic-bezier(0.65, 0, 0.35, 1)` | Fly-to. |
| `motion.easing.linear` | `--ease-linear` | `cubic-bezier(0, 0, 1, 1)` | Arc dash travel. |

## Component patterns

### Glass panel

Translucent square panel with a faint 1px stroke, four corner brackets in `border.strong` and a 1px inner top highlight. Title row is 36px. Never placed over the instrument ring.

| Property | Token / value |
|---|---|
| `component.panel.background` | `{color.surface.panel}` |
| `component.panel.border` | `{color.border.subtle}` |
| `component.panel.bracket` | `{radius.bracket}` |
| `component.panel.bracketColor` | `{color.border.strong}` |
| `component.panel.blur` | `{blur.panel}` |
| `component.panel.edge` | `{elevation.innerEdge}` |
| `component.panel.padding` | `{space.5}` |
| `component.panel.title` | `{typography.heading}` |

### Instrument ring

SVG ring concentric with the globe (radius = globe radius x 1.14). Ticks every 5 degrees. Top arc (200 to 340 degrees): seven topic segments, labels on a text path. Bottom arc (20 to 160 degrees): 7 x 24 hourly bars radiating outward, length proportional to volume; the selected range is drawn in `hud.ringActive` with two handles. Recomputed on zoom and resize.

| Property | Token / value |
|---|---|
| `component.ring.track` | `{color.hud.ringTrack}` |
| `component.ring.tick` | `{color.hud.ringTick}` |
| `component.ring.active` | `{color.hud.ringActive}` |
| `component.ring.label` | `{typography.label}` |
| `component.ring.radiusFactor` | `1.14` |
| `component.ring.barMaxLength` | `34px` |

### Chip

Pill, 26px. Used inside panels (suggested prompts, entity tags). Active chips get `accent.soft` fill and `elevation.glowSm`.

| Property | Token / value |
|---|---|
| `component.chip.height` | `26px` |
| `component.chip.radius` | `{radius.pill}` |
| `component.chip.border` | `{color.border.default}` |
| `component.chip.activeFill` | `{color.accent.soft}` |
| `component.chip.activeGlow` | `{elevation.glowSm}` |
| `component.chip.label` | `{typography.label}` |

### HUD readout

Unit label above a light-weight mono value, bracketed by two 6px corner ticks. Used for UTC time, volume and coordinates.

| Property | Token / value |
|---|---|
| `component.readout.value` | `{typography.readoutXl}` |
| `component.readout.valueColor` | `{color.text.primary}` |
| `component.readout.label` | `{typography.dataSm}` |
| `component.readout.labelColor` | `{color.text.muted}` |
| `component.readout.bracket` | `{color.border.strong}` |

### Lock-on preview

Four corner brackets converge on the location (`motion.duration.lockOn`) and a leader line runs from the reticle to a 340px card docked at the top of the right column (the card does not follow the dot, so it never covers the globe). Card: image in cyan duotone with static scanlines (an orbital crop of the night texture when `image_url` is missing), headline, source and time, topic mix, a semicircular tone gauge with signed score, a 24 h sparkline, entity chips and the AI brief.

| Property | Token / value |
|---|---|
| `component.preview.width` | `340px` |
| `component.preview.background` | `{color.surface.overlay}` |
| `component.preview.blur` | `{blur.overlay}` |
| `component.preview.border` | `{color.border.strong}` |
| `component.preview.glow` | `{elevation.glowMd}` |
| `component.preview.reticle` | `{color.hud.reticle}` |
| `component.preview.enter` | `{motion.duration.lockOn}` |
| `component.preview.easing` | `{motion.easing.emphasized}` |

### Connection arc

Great-circle arc with an animated dash (length 0.4, gap 0.2) travelling from the earlier story to the later one. Selected thread uses `arc.highlight` with stroke 0.6; others `arc.default`, static, stroke 0.3.

| Property | Token / value |
|---|---|
| `component.connection.stroke` | `0.3` |
| `component.connection.strokeActive` | `0.6` |
| `component.connection.color` | `{color.arc.coverage}` |
| `component.connection.highlight` | `{color.arc.highlight}` |
| `component.connection.dashLength` | `0.4` |
| `component.connection.dashGap` | `0.2` |
| `component.connection.dashTime` | `{motion.duration.arcDash}` |

### Co-pilot console

Glass panel bottom-left. Assistant text streams with a block cursor; tool activity shows as a single status line with a progress tick; citations are chips that fly the globe and lock on.

| Property | Token / value |
|---|---|
| `component.console.background` | `{color.surface.panel}` |
| `component.console.prose` | `{typography.body}` |
| `component.console.status` | `{typography.dataSm}` |
| `component.console.statusColor` | `{color.accent.strong}` |
| `component.console.citationFill` | `{color.accent.soft}` |
| `component.console.inputBackground` | `{color.bg.inset}` |

## Accessibility check (computed)

WCAG 2.x contrast ratios, generated from the token values (translucent surfaces composited over `bg.page`). Target: 4.5 for text, 3.0 for large text and non-text UI.

| Mode | Surface | Foreground | Ratio | Target | Result |
|---|---|---|---|---|---|
| dark | bg.page | text.primary | 18.60 | 4.5 | pass |
| dark | bg.page | text.secondary | 12.47 | 4.5 | pass |
| dark | bg.page | text.muted | 8.20 | 4.5 | pass |
| dark | bg.page | accent.primary (as text) | 11.55 | 4.5 | pass |
| dark | bg.page | border.strong (UI) | 5.83 | 3 | pass |
| dark | bg.page | hud.ringTick (UI) | 3.16 | 3 | pass |
| dark | bg.page | sentiment.n3 (mark) | 6.83 | 3 | pass |
| dark | surface.panel (glass) | text.primary | 17.60 | 4.5 | pass |
| dark | surface.panel (glass) | text.secondary | 11.81 | 4.5 | pass |
| dark | surface.panel (glass) | text.muted | 7.76 | 4.5 | pass |
| dark | surface.panel (glass) | accent.primary (as text) | 10.93 | 4.5 | pass |
| dark | surface.panel (glass) | border.strong (UI) | 5.78 | 3 | pass |
| dark | surface.panel (glass) | hud.ringTick (UI) | 3.25 | 3 | pass |
| dark | surface.panel (glass) | sentiment.n3 (mark) | 6.47 | 3 | pass |
| dark | surface.overlay | text.primary | 17.48 | 4.5 | pass |
| dark | surface.overlay | text.secondary | 11.73 | 4.5 | pass |
| dark | surface.overlay | text.muted | 7.71 | 4.5 | pass |
| dark | surface.overlay | accent.primary (as text) | 10.85 | 4.5 | pass |
| dark | surface.overlay | border.strong (UI) | 5.77 | 3 | pass |
| dark | surface.overlay | hud.ringTick (UI) | 3.25 | 3 | pass |
| dark | surface.overlay | sentiment.n3 (mark) | 6.42 | 3 | pass |

Glass contrast is computed against `bg.page`. Over the bright parts of the night texture (city lights) contrast drops, which is why panels sit at the screen edges where the globe is not, and why the preview card uses the more opaque `surface.overlay`.

## Mobile adaptation

- The globe stays full-bleed. The ring keeps its ticks and histogram but drops text labels; topics move to a swipeable chip row under the brand, and the time arc becomes a thumb-wheel at the bottom edge (drag horizontally to scrub hours, tap a day).
- Threads, analysis and co-pilot become one bottom sheet with three tabs (peek height 88px, showing the live status line).
- Lock-on preview docks to the bottom sheet's top edge instead of floating; the reticle stays on the globe.
- Low-power mode is on by default on mobile: no backdrop blur, no arc dashes, atmosphere off.

## Do and don't

- Do keep glow on strokes and dots. Don't put glow or text-shadow on paragraphs.
- Do keep the ring unobstructed; panels collapse before they overlap it.
- Don't add continuous scanline sweeps. The scanline texture is static; one sweep may run when new data lands.
- Don't use Orbitron outside the wordmark.
