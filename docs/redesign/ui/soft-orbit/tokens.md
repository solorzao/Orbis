# Soft Orbit: design tokens

> Signal Desk's features in a calm, frosted cockpit: rounded glass panels float over a drifting globe wrapped in orbital rings, with cyan easing into periwinkle and lavender.

Soft Orbit answers the owner's feedback on Signal Desk ("too much like a government website"; "sci-fi mixed with soft, elegant UI"). It keeps Signal Desk's information architecture and every feature surface, and changes the feel: the boxed grid is gone, panels are rounded frosted glass floating over a full-bleed globe, and only three things are open by default (threads, co-pilot, the hover card). Everything else opens on demand. The sci-fi comes from orbital rings around the globe, a soft circular reticle, a faint starfield and a holographic edge light on panels, all kept quiet. Its one memorable device is the **aurora gradient**: brand cyan easing into periwinkle and lavender, used for the active thread's arcs, the replay control and the panel edge light, and nowhere else.

Machine-readable twin: [`tokens.json`](./tokens.json) (W3C Design Tokens format: `$value`, `$type`, `$description`, `{alias}` references). Mockup: [`mockup.html`](./mockup.html). Its `:root` block is generated from the same source, so the three never drift.

**Modes:** dark only. Frosted glass and soft glow depend on a dark, slightly warm night sky. Observatory is the direction that ships a matching light theme; if Soft Orbit needs one later, derive it from Observatory's daylight roles rather than inverting these values.

## Principles

1. Float, don't dock. Panels are frosted glass with 20 to 28px radii, separated by space instead of rules.
2. Progressive disclosure: three surfaces open by default (threads, co-pilot, hover card). The inspector, entity tracker and board open on request and close back to a pill.
3. Aurora (cyan to periwinkle to lavender) marks what is alive or selected: the active thread, the replay, the edge light of the focused panel. Everything else is quiet neutrals.
4. Lighter type: Space Grotesk at 400 and 500, never bold. JetBrains Mono only for numbers, at 300 or 400.
5. Calm motion: the globe drifts a few degrees and back, thread arcs flow slowly, orbital rings turn once every two minutes. All of it stops with prefers-reduced-motion or on first interaction with the globe.
6. Legibility over atmosphere: text sits on a scrim inside the glass where it is dense, every colour keeps its printed number, and text contrast is AA.

## Brand lockup (frozen)

Shared by all three directions and copied from `frontend/src/app/page.tsx`. Treat it as an asset, not a style.

| Part | Spec |
|---|---|
| Logo | `/Orbis_logo_50_resize.png`, 40px (28px mobile), `drop-shadow(0 0 12px rgba(0,212,255,.5))` |
| Wordmark | "Orbis", Orbitron 700, 18px/28px (14px/20px mobile), uppercase, tracking 0.2em, `text-shadow: 0 0 30px rgba(0,212,255,.4)`, colour #c8e6f8 dark / #1e293b light |
| Motto | "Every Story, Everywhere", system-ui 500, 9px, uppercase, tracking 0.3em, colour #4482a8 dark / #5c6f8a light (raised from #3a7090 / #94a3b8 to meet WCAG AA, about 4.6:1), hidden below 640px |
| Layout | Logo then a text block, 12px gap (8px mobile), pinned top-left at 20px/24px (12px mobile) |

## Colour roles

### Night sky

| Token | CSS var | Value | Use |
|---|---|---|---|
| `color.bg.page` | `--bg-page` | `#0d0c17` | Deep night with a faint warm violet undertone. |
| `color.bg.inset` | `--bg-inset` | `rgba(9, 8, 20, 0.55)` | Wells inside glass: inputs, chart plots. |
| `color.bg.hazeA` | `--bg-haze-a` | `rgba(0, 212, 255, 0.10)` | Cyan haze, top-left radial glow of the sky. |
| `color.bg.hazeB` | `--bg-haze-b` | `rgba(170, 140, 255, 0.12)` | Lavender haze, bottom-right radial glow of the sky. |
| `color.bg.star` | `--bg-star` | `rgba(220, 225, 255, 0.55)` | Starfield points (static, 1px). |

### Frosted surfaces

| Token | CSS var | Value | Use |
|---|---|---|---|
| `color.surface.glass` | `--surface-glass` | `rgba(26, 24, 46, 0.62)` | Frosted panel body (with blur.glass). Low-power fallback: #1a182c. |
| `color.surface.scrim` | `--surface-scrim` | `rgba(14, 12, 28, 0.55)` | Inner scrim behind dense text inside glass (keeps AA over bright globe areas). |
| `color.surface.raised` | `--surface-raised` | `rgba(255, 255, 255, 0.05)` | Rows, chips and cards inside glass. |
| `color.surface.hover` | `--surface-hover` | `rgba(255, 255, 255, 0.08)` | Hover wash. |
| `color.surface.selected` | `--surface-selected` | `rgba(0, 212, 255, 0.12)` | Selected wash. |
| `color.surface.sheet` | `--surface-sheet` | `rgba(20, 18, 36, 0.86)` | Full-screen sheets (board), more opaque. |

### Borders and edge light

| Token | CSS var | Value | Use |
|---|---|---|---|
| `color.border.subtle` | `--border-subtle` | `rgba(214, 218, 255, 0.08)` | Default glass outline. |
| `color.border.default` | `--border-default` | `rgba(214, 218, 255, 0.14)` | Controls, chips. |
| `color.border.strong` | `--border-strong` | `rgba(214, 218, 255, 0.40)` | Chart axes, focused control outline. |
| `color.border.focus` | `--border-focus` | `#7fe6ff` | Keyboard focus ring (2px, offset 3px). |
| `color.border.edgeA` | `--border-edge-a` | `rgba(0, 212, 255, 0.45)` | Holographic edge light, start (top-left). |
| `color.border.edgeB` | `--border-edge-b` | `rgba(195, 166, 255, 0.35)` | Holographic edge light, end (bottom-right). |

### Text

| Token | CSS var | Value | Use |
|---|---|---|---|
| `color.text.primary` | `--text-primary` | `#eef0ff` | Titles, values. |
| `color.text.secondary` | `--text-secondary` | `#c0c3e0` | Body copy. |
| `color.text.muted` | `--text-muted` | `#9a9ec2` | Captions, labels, timestamps. |
| `color.text.inverse` | `--text-inverse` | `#0b0a16` | Text on aurora or cyan fills. |

### Accent and aurora

| Token | CSS var | Value | Use |
|---|---|---|---|
| `color.accent.primary` | `--accent-primary` | `#00d4ff` | Brand cyan, the anchor of the aurora. |
| `color.accent.strong` | `--accent-strong` | `#7fe6ff` | Hover, focus, cyan text on glass. |
| `color.accent.soft` | `--accent-soft` | `rgba(0, 212, 255, 0.14)` | Active chip fill. |
| `color.accent.on` | `--accent-on` | `#0b0a16` | Foreground on cyan or aurora. |
| `color.accent.periwinkle` | `--accent-periwinkle` | `#8b9cff` | Aurora midpoint. |
| `color.accent.lavender` | `--accent-lavender` | `#c3a6ff` | Aurora end. |

### Status signals

| Token | CSS var | Value | Use |
|---|---|---|---|
| `color.signal.live` | `--signal-live` | `#7ee0b5` | Live indicator (soft mint). |
| `color.signal.warning` | `--signal-warning` | `#f5c27a` | Surges, stale data. |
| `color.signal.danger` | `--signal-danger` | `#f28b95` | Offline, errors. |

### Globe

| Token | CSS var | Value | Use |
|---|---|---|---|
| `color.globe.ocean` | `--globe-ocean` | `#151433` | Sphere colour (no photo texture). |
| `color.globe.land` | `--globe-land` | `#6f78c9` | Dotted land (hex dots), drawn at 55% opacity. |
| `color.globe.atmosphere` | `--globe-atmosphere` | `#8fb4ff` | Soft periwinkle atmosphere (altitude 0.24). |

### Connection arcs

| Token | CSS var | Value | Use |
|---|---|---|---|
| `color.arc.coverage` | `--arc-coverage` | `rgba(180, 190, 255, 0.30)` | Co-coverage link. Width encodes story count. |
| `color.arc.highlight` | `--arc-highlight` | `#7fe6ff` | Inspected link. |
| `color.arc.muted` | `--arc-muted` | `rgba(180, 190, 255, 0.10)` | Filtered-out links. |
| `color.arc.relationCooperation` | `--arc-relation-cooperation` | `#8fb8ff` | Actor relation, cooperation (later phase). |
| `color.arc.relationConflict` | `--arc-relation-conflict` | `#f2949c` | Actor relation, conflict (later phase). |

### Orbital instrumentation

| Token | CSS var | Value | Use |
|---|---|---|---|
| `color.orbit.ring` | `--orbit-ring` | `rgba(190, 200, 255, 0.16)` | Orbital ellipses around the globe. |
| `color.orbit.tick` | `--orbit-tick` | `rgba(190, 200, 255, 0.30)` | Ring ticks, satellite dots. |
| `color.orbit.reticle` | `--orbit-reticle` | `#bfefff` | Soft circular reticle on the hovered place. |

## Data-viz palettes

### Sentiment (diverging, -1 to +1)

Dusty rose to sea-glass teal through a lilac grey: desaturated so it sits calmly on glass, with the two ends far apart in lightness for colour-blind readers. Every value also prints its signed score.

| Token | CSS var | Value | Use |
|---|---|---|---|
| `dataviz.sentiment.n3` | `--sentiment-n3` | `#f08a94` | Strongly negative (<= -0.6). |
| `dataviz.sentiment.n2` | `--sentiment-n2` | `#e6a5aa` | Negative. |
| `dataviz.sentiment.n1` | `--sentiment-n1` | `#cdb8c4` | Slightly negative. |
| `dataviz.sentiment.neutral` | `--sentiment-neutral` | `#a9abc8` | Neutral. |
| `dataviz.sentiment.p1` | `--sentiment-p1` | `#acd4d2` | Slightly positive. |
| `dataviz.sentiment.p2` | `--sentiment-p2` | `#8bdcc9` | Positive. |
| `dataviz.sentiment.p3` | `--sentiment-p3` | `#62dcbc` | Strongly positive (>= 0.6). |

Binning: `n3` <= -0.6 < `n2` <= -0.3 < `n1` <= -0.1 < `neutral` < 0.1 <= `p1` < 0.3 <= `p2` < 0.6 <= `p3`. Always print the signed score (e.g. `-0.42`) next to the colour; colour is never the only channel.

### Topics (categorical)

Pastel versions of the current topic hues, matched in lightness so no topic shouts. Technology moves from cyan to a sky blue so cyan stays the brand's.

| Token | CSS var | Value | Use |
|---|---|---|---|
| `dataviz.topic.all` | `--topic-all` | `#c0c3e0` | No topic filter. |
| `dataviz.topic.politics` | `--topic-politics` | `#ab9dff` | Politics. |
| `dataviz.topic.conflict` | `--topic-conflict` | `#ff8f9c` | Conflict. |
| `dataviz.topic.technology` | `--topic-technology` | `#7db9ff` | Technology (was #06B6D4). |
| `dataviz.topic.climate` | `--topic-climate` | `#72ddb2` | Climate. |
| `dataviz.topic.economy` | `--topic-economy` | `#f4c97c` | Economy. |
| `dataviz.topic.health` | `--topic-health` | `#f5a0d0` | Health. |

## Typography

An airy scale on a 14px body with generous line height. Weight does little work (400 and 500 only); size and colour carry hierarchy.

| Font role | Stack | Use |
|---|---|---|
| `font.family.brand` (`--font-brand`) | Orbitron, sans-serif | Wordmark only. |
| `font.family.heading` (`--font-heading`) | Space Grotesk, system-ui, sans-serif | Titles, labels and controls, at 400 to 500. |
| `font.family.body` (`--font-body`) | Space Grotesk, system-ui, sans-serif | Prose at 400. |
| `font.family.mono` (`--font-mono`) | JetBrains Mono, ui-monospace, monospace | Numbers only: counts, scores, times, coordinates. |

| Style | Family | Size / line | Weight | Tracking | Use |
|---|---|---|---|---|---|
| `typography.title` | Space Grotesk | 19/26 | 400 | -0.01em | Hover card place name, inspector titles. |
| `typography.heading` | Space Grotesk | 15/22 | 500 | 0 | Panel titles, headlines in cards. |
| `typography.body` | Space Grotesk | 14/22 | 400 | 0 | Co-pilot answers, summaries. |
| `typography.bodySm` | Space Grotesk | 13/20 | 400 | 0 | List items, secondary prose. |
| `typography.label` | Space Grotesk | 12/16 | 400 | 0.01em | Labels and pills (sentence case). |
| `typography.dataXl` | JetBrains Mono | 22/28 | 300 | 0 | Clock, hero numbers. Uses `"tnum" 1, "zero" 1`. |
| `typography.dataLg` | JetBrains Mono | 16/22 | 300 | 0 | Readouts in panels. Uses `"tnum" 1`. |
| `typography.data` | JetBrains Mono | 12/16 | 400 | 0 | Scores, counts, times. Uses `"tnum" 1`. |
| `typography.dataSm` | JetBrains Mono | 11/14 | 400 | 0 | Axis ticks, coordinates. Uses `"tnum" 1`. |

CSS: each style is a `font` shorthand, e.g. `font: var(--type-title);`, plus `letter-spacing: var(--tracking-*)` where tracking is non-zero.

## Space, radii, borders

8px rhythm with room to breathe: 20px panel padding, 12px between rows, 24px between floating panels and the screen edge.

| Space | `0` | `1` | `2` | `3` | `4` | `5` | `6` | `7` | `8` |
|---|---|---|---|---|---|---|---|---|---|
| px | 0 | 4 | 8 | 12 | 16 | 20 | 24 | 32 | 48 |

Generously rounded and nested: outer radius = inner radius + padding, so corners stay concentric.

| Radius | Value | Use |
|---|---|---|
| `radius.sm` | 10px | Thumbnails, inputs inside cards. |
| `radius.md` | 16px | Cards and rows inside panels. |
| `radius.lg` | 22px | Hover card, inspector. |
| `radius.xl` | 28px | Floating panels and sheets. |
| `radius.pill` | 999px | Chips, buttons, the timeline capsule. |

| Border width | Value | Use |
|---|---|---|
| `borderWidth.hairline` | 1px | Glass outlines and edge light. |
| `borderWidth.focus` | 2px | Focus ring. |

| Blur | Value | Use |
|---|---|---|
| `blur.glass` | 24px | Floating panels (backdrop-filter, with saturate 1.3). 0 in low-power mode. |
| `blur.sheet` | 32px | Board sheet. |

## Elevation and glow

Soft, wide shadows that read as distance, plus an inner top light. Glow is reserved for the aurora and focus.

| Token | Value | Use |
|---|---|---|
| `elevation.float` | `0px 24px 64px -12px rgba(3, 2, 12, 0.55), inset 0px 1px 0px 0px rgba(255, 255, 255, 0.07)` | Floating glass panels. |
| `elevation.lifted` | `0px 30px 80px -10px rgba(3, 2, 12, 0.65), inset 0px 1px 0px 0px rgba(255, 255, 255, 0.09)` | Hover card, sheets. |
| `elevation.glow` | `0px 0px 28px 0px rgba(0, 212, 255, 0.28)` | Aurora controls (replay button), active thread. |

## Motion

Eased and unhurried. Ambient motion (drift, arc flow, ring turn) is decorative and therefore optional: it stops under `prefers-reduced-motion: reduce`, in low-power mode, and the moment the user grabs the globe.

| Token | CSS var | Value | Use |
|---|---|---|---|
| `motion.duration.fast` | `--dur-fast` | `180ms` | Hover, pill toggles. |
| `motion.duration.base` | `--dur-base` | `280ms` | Card content change. |
| `motion.duration.slow` | `--dur-slow` | `480ms` | Panel open and close (progressive disclosure). |
| `motion.duration.flyTo` | `--dur-fly-to` | `1600ms` | Camera move. |
| `motion.duration.arcFlow` | `--dur-arc-flow` | `6000ms` | One slow dash cycle along the active thread's arcs. |
| `motion.duration.drift` | `--dur-drift` | `40000ms` | Globe drift period (a few degrees out and back). |
| `motion.duration.orbit` | `--dur-orbit` | `120000ms` | One turn of an orbital ring. |
| `motion.easing.out` | `--ease-out` | `cubic-bezier(0.22, 1, 0.36, 1)` | Opening, appearing (ease-out-quint). |
| `motion.easing.inOut` | `--ease-in-out` | `cubic-bezier(0.65, 0, 0.35, 1)` | Camera and drift. |
| `motion.easing.standard` | `--ease-standard` | `cubic-bezier(0.2, 0, 0, 1)` | Small state changes. |

## Component patterns

### Floating glass panel

Rounded frosted panel with an inner top light, a soft drop shadow and, when focused, a 1px holographic edge light (cyan to lavender gradient border drawn with a masked pseudo-element). Dense text sits on `surface.scrim`.

| Property | Token / value |
|---|---|
| `component.glassPanel.background` | `{color.surface.glass}` |
| `component.glassPanel.scrim` | `{color.surface.scrim}` |
| `component.glassPanel.border` | `{color.border.subtle}` |
| `component.glassPanel.edgeStart` | `{color.border.edgeA}` |
| `component.glassPanel.edgeEnd` | `{color.border.edgeB}` |
| `component.glassPanel.radius` | `{radius.xl}` |
| `component.glassPanel.blur` | `{blur.glass}` |
| `component.glassPanel.shadow` | `{elevation.float}` |
| `component.glassPanel.padding` | `{space.5}` |

### Pill (chip, toggle, button)

Every control is a pill. Inactive: transparent with `border.default`. Active: `accent.soft` fill and cyan text. Primary actions use the aurora gradient with dark text.

| Property | Token / value |
|---|---|
| `component.pill.height` | `32px` |
| `component.pill.heightSm` | `26px` |
| `component.pill.radius` | `{radius.pill}` |
| `component.pill.border` | `{color.border.default}` |
| `component.pill.activeFill` | `{color.accent.soft}` |
| `component.pill.activeText` | `{color.accent.strong}` |
| `component.pill.label` | `{typography.label}` |

### Aurora gradient

linear-gradient(120deg, cyan, periwinkle 55%, lavender). Used for the replay button, the active thread's arcs and the focus edge light. Never behind text other than `text.inverse`.

| Property | Token / value |
|---|---|
| `component.aurora.start` | `{color.accent.primary}` |
| `component.aurora.mid` | `{color.accent.periwinkle}` |
| `component.aurora.end` | `{color.accent.lavender}` |
| `component.aurora.glow` | `{elevation.glow}` |

### Hover card

340px glass card beside the hovered place, joined by a soft curved leader to a circular reticle. Image (rounded 10px) or a topic glyph on a soft gradient when there is no image; conflict images are blurred until clicked.

| Property | Token / value |
|---|---|
| `component.preview.width` | `340px` |
| `component.preview.background` | `{color.surface.glass}` |
| `component.preview.radius` | `{radius.lg}` |
| `component.preview.shadow` | `{elevation.lifted}` |
| `component.preview.reticle` | `{color.orbit.reticle}` |
| `component.preview.enter` | `{motion.duration.base}` |
| `component.preview.easing` | `{motion.easing.out}` |

### Timeline capsule

A pill-shaped capsule at the bottom centre: aurora play button for replay, a smooth 7-day area chart of story volume with the window as a soft highlight, day labels, a last-visit marker and presets.

| Property | Token / value |
|---|---|
| `component.timeline.height` | `84px` |
| `component.timeline.radius` | `{radius.pill}` |
| `component.timeline.fill` | `{color.accent.periwinkle}` |
| `component.timeline.window` | `{color.accent.soft}` |
| `component.timeline.playhead` | `{color.text.primary}` |

### Orbital rings and reticle

Two tilted ellipses (rx 1.3R, ry 0.36R) and one circle at 1.08R with ticks every 15 degrees, drawn in SVG over the globe. Rings turn once every `motion.duration.orbit`. The reticle is two concentric circles with four short ticks.

| Property | Token / value |
|---|---|
| `component.orbitRing.ring` | `{color.orbit.ring}` |
| `component.orbitRing.tick` | `{color.orbit.tick}` |
| `component.orbitRing.reticle` | `{color.orbit.reticle}` |
| `component.orbitRing.period` | `{motion.duration.orbit}` |

### Connection arc

Active thread: aurora gradient, stroke 0.55, long slow dash (0.9 on, 0.1 off) flowing over `motion.duration.arcFlow`. Co-coverage: faint periwinkle, static. Inspected link: `arc.highlight`. A floating pill at the inspected arc's midpoint names the link.

| Property | Token / value |
|---|---|
| `component.connection.stroke` | `0.3` |
| `component.connection.strokeActive` | `0.55` |
| `component.connection.coverage` | `{color.arc.coverage}` |
| `component.connection.highlight` | `{color.arc.highlight}` |
| `component.connection.flow` | `{motion.duration.arcFlow}` |

### Investigation board (split view)

A large frosted sheet on the left 58% of the screen while the globe slides right and mirrors the pins (rings on pinned places, aurora arcs between them). Pins are rounded cards; same-thread edges use the aurora gradient, shared-entity edges are quiet grey, covered-together edges are dashed, and links you draw yourself are warm amber and labelled.

| Property | Token / value |
|---|---|
| `component.board.background` | `{color.surface.sheet}` |
| `component.board.blur` | `{blur.sheet}` |
| `component.board.radius` | `{radius.xl}` |
| `component.board.pinRadius` | `{radius.md}` |
| `component.board.sameThread` | `{color.accent.periwinkle}` |
| `component.board.user` | `{color.signal.warning}` |

### Co-pilot

Right-hand glass panel. Context pills show what the co-pilot sees; answers are prose with small numbered citation pills; suggested actions are a row of pills; tool activity is a single quiet line.

| Property | Token / value |
|---|---|
| `component.console.background` | `{color.surface.glass}` |
| `component.console.prose` | `{typography.body}` |
| `component.console.citationFill` | `{color.accent.soft}` |
| `component.console.actionFill` | `{color.surface.raised}` |
| `component.console.inputBackground` | `{color.bg.inset}` |

## Accessibility check (computed)

WCAG 2.x contrast ratios, generated from the token values (translucent surfaces composited over `bg.page`). Target: 4.5 for text, 3.0 for large text and non-text UI.

| Mode | Surface | Foreground | Ratio | Target | Result |
|---|---|---|---|---|---|
| dark | bg.page | text.primary | 17.14 | 4.5 | pass |
| dark | bg.page | text.secondary | 11.20 | 4.5 | pass |
| dark | bg.page | text.muted | 7.43 | 4.5 | pass |
| dark | bg.page | accent.strong (as text) | 13.55 | 4.5 | pass |
| dark | bg.page | border.strong (UI) | 3.08 | 3 | pass |
| dark | bg.page | sentiment.n3 (mark) | 8.10 | 3 | pass |
| dark | glass (over sky) | text.primary | 16.05 | 4.5 | pass |
| dark | glass (over sky) | text.secondary | 10.49 | 4.5 | pass |
| dark | glass (over sky) | text.muted | 6.96 | 4.5 | pass |
| dark | glass (over sky) | accent.strong (as text) | 12.69 | 4.5 | pass |
| dark | glass (over sky) | border.strong (UI) | 3.11 | 3 | pass |
| dark | glass (over sky) | sentiment.n3 (mark) | 7.59 | 3 | pass |
| dark | glass + scrim | text.primary | 16.38 | 4.5 | pass |
| dark | glass + scrim | text.secondary | 10.71 | 4.5 | pass |
| dark | glass + scrim | text.muted | 7.10 | 4.5 | pass |
| dark | glass + scrim | accent.strong (as text) | 12.95 | 4.5 | pass |
| dark | glass + scrim | border.strong (UI) | 3.11 | 3 | pass |
| dark | glass + scrim | sentiment.n3 (mark) | 7.74 | 3 | pass |

Contrast is computed against the night sky. Over bright parts of the globe the glass is lighter than this, which is why dense text sits on `surface.scrim` and why the hover card is placed beside the place, over ocean or space where possible.

## Mobile adaptation

- Floating panels become one bottom sheet (radius 28px on top) with pill tabs: Threads, Co-pilot, Inspect. Peek height shows the active thread and the replay button.
- The hover card becomes a tap card docked above the sheet; the reticle stays on the globe.
- The timeline capsule shrinks to play button, current window and presets; the area chart moves into the Threads tab.
- Orbital rings stay (they are cheap SVG); drift and arc flow are off by default on mobile.

## Do and don't

- Do leave space between panels; never let two panels touch.
- Do keep the aurora for live or selected things. A second gradient anywhere else dilutes it.
- Don't use weights above 500 or all-caps labels (the brand motto is the exception).
- Don't put body text directly on glass over the globe without the scrim.
