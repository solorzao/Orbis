# Signal Desk: design tokens

> A quiet, dense analyst's desk where the globe is one instrument among watchlists, trend lines and tables.

**Status: the dense reference.** The owner liked its features but said it "looks too much like a government website". Soft Orbit and Observatory carry the same features in a softer form; Signal Desk stays as the benchmark for information density.

Signal Desk treats Orbis like a trading floor for world news. Everything is opaque, aligned to a 4px grid and quiet by default, so the only things that move or glow are the things that changed. The globe is a matte instrument (hex-dot land, extruded columns for volume, thin static arcs) rather than a spectacle, which makes it the cheapest of the three directions to render. Brand cyan is reserved for interaction and selection; colour elsewhere is data.

Machine-readable twin: [`tokens.json`](./tokens.json) (W3C Design Tokens format: `$value`, `$type`, `$description`, `{alias}` references). Mockup: [`mockup.html`](./mockup.html). Its `:root` block is generated from the same source, so the three never drift.

**Modes:** dark (default) and light. `$value` is dark; the light value lives in `$extensions["co.orbisapp"].modes.light`. CSS switches with `[data-theme="light"]` on `<html>`, same as the current app.

## Principles

1. Opaque panels, no backdrop blur. Density comes from alignment, not from translucency.
2. Cyan means "you did this": focus, selection, the active filter, the live cursor. Never decoration.
3. Numbers are set in JetBrains Mono with tabular figures so columns line up and values can be scanned.
4. Labels are sentence case in Space Grotesk. No tracked capitals except the frozen brand motto.
5. Motion only answers input: hover, select, fly-to. Nothing loops, and the globe does not auto-rotate.
6. Every colour-coded value also prints its number (sentiment -0.42, volume +38%).

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

| Token | CSS var | Dark | Light | Use |
|---|---|---|---|---|
| `color.bg.page` | `--bg-page` | `#060b10` | `#e9eef2` | App canvas behind globe and panels. Replaces the current --bg-page. |
| `color.bg.inset` | `--bg-inset` | `#04080c` | `#f5f8fa` | Wells: inputs, chart plots, the globe viewport. |

### Surfaces

| Token | CSS var | Dark | Light | Use |
|---|---|---|---|---|
| `color.surface.panel` | `--surface-panel` | `#0a121a` | `#ffffff` | Opaque panel body. |
| `color.surface.raised` | `--surface-raised` | `#0f1a24` | `#f3f6f8` | Panel header strips, table header rows. |
| `color.surface.overlay` | `--surface-overlay` | `rgba(10, 18, 26, 0.97)` | `rgba(255, 255, 255, 0.98)` | Hover preview and menus that float over the globe. |
| `color.surface.hover` | `--surface-hover` | `#13202c` | `#eef3f6` | Row and button hover. |
| `color.surface.selected` | `--surface-selected` | `#0c2533` | `#dff2f8` | Selected row or item (cyan-tinted). |

### Borders

| Token | CSS var | Dark | Light | Use |
|---|---|---|---|---|
| `color.border.subtle` | `--border-subtle` | `#16222d` | `#e3e9ee` | Row dividers inside a panel. |
| `color.border.default` | `--border-default` | `#22313e` | `#cfd8e0` | Panel outlines and gutters. |
| `color.border.strong` | `--border-strong` | `#5b7287` | `#6f8292` | Control outlines, chart axes, inactive chip edges. |
| `color.border.focus` | `--border-focus` | `#00d4ff` | `#006d92` | Keyboard focus ring (2px, 2px offset). |

### Text

| Token | CSS var | Dark | Light | Use |
|---|---|---|---|---|
| `color.text.primary` | `--text-primary` | `#dbe7f0` | `#0f1c26` | Headlines, values, active labels. |
| `color.text.secondary` | `--text-secondary` | `#9ab0c1` | `#3d5466` | Body copy and secondary values. |
| `color.text.muted` | `--text-muted` | `#7690a3` | `#54687a` | Column headers, captions, timestamps. |
| `color.text.inverse` | `--text-inverse` | `#04121a` | `#ffffff` | Text on accent fills. |

### Accent (brand cyan)

| Token | CSS var | Dark | Light | Use |
|---|---|---|---|---|
| `color.accent.primary` | `--accent-primary` | `#00d4ff` | `#006d92` | Brand cyan. Interactive and selected state only. |
| `color.accent.strong` | `--accent-strong` | `#5fe3ff` | `#005677` | Hover/pressed accent. |
| `color.accent.soft` | `--accent-soft` | `rgba(0, 212, 255, 0.12)` | `rgba(0, 109, 146, 0.10)` | Tinted fill behind active chips and brush ranges. |
| `color.accent.on` | `--accent-on` | `#021018` | `#ffffff` | Foreground on solid accent. |

### Status signals

| Token | CSS var | Dark | Light | Use |
|---|---|---|---|---|
| `color.signal.live` | `--signal-live` | `#2fd38a` | `#12825a` | Live data indicator. |
| `color.signal.warning` | `--signal-warning` | `#f2b33d` | `#9a6200` | Stale data, partial results, rate limit. |
| `color.signal.danger` | `--signal-danger` | `#ff6b6b` | `#c62828` | Offline, failed request. |

### Globe

| Token | CSS var | Dark | Light | Use |
|---|---|---|---|---|
| `color.globe.ocean` | `--globe-ocean` | `#0b1620` | `#d9e3ea` | Sphere material colour (no photo texture). |
| `color.globe.land` | `--globe-land` | `#2b4558` | `#8ea2b2` | Hex-dot land polygons. |
| `color.globe.atmosphere` | `--globe-atmosphere` | `#1b5f7a` | `#9cc7da` | Thin atmosphere rim (altitude 0.1). |
| `color.globe.graticule` | `--globe-graticule` | `#132331` | `#c5d2dc` | Optional 30-degree graticule. |

### Connection arcs

| Token | CSS var | Dark | Light | Use |
|---|---|---|---|---|
| `color.arc.coverage` | `--arc-coverage` | `rgba(154, 176, 193, 0.42)` | `rgba(61, 84, 102, 0.45)` | Co-coverage link (places named in the same stories). Neutral; width encodes story count. |
| `color.arc.highlight` | `--arc-highlight` | `#00d4ff` | `#006d92` | Links of the hovered, selected or inspected item. |
| `color.arc.muted` | `--arc-muted` | `rgba(154, 176, 193, 0.10)` | `rgba(61, 84, 102, 0.12)` | Links outside the current filter, kept for context. |
| `color.arc.relationCooperation` | `--arc-relation-cooperation` | `#5b9dff` | `#2a62c9` | Actor relation, cooperation (later phase, GDELT Events). |
| `color.arc.relationConflict` | `--arc-relation-conflict` | `#ff6b5e` | `#c43a2e` | Actor relation, conflict (later phase, GDELT Events). |

## Data-viz palettes

### Sentiment (diverging, -1 to +1)

Red to teal through a warm grey. Red keeps the meaning users learned from the current app; teal replaces green so the two ends also differ in lightness (safer for red-green colour blindness). Neutral is grey, not amber, because amber reads as a warning.

| Token | CSS var | Dark | Light | Use |
|---|---|---|---|---|
| `dataviz.sentiment.n3` | `--sentiment-n3` | `#ff5a4e` | `#c62d22` | Strongly negative (<= -0.6). |
| `dataviz.sentiment.n2` | `--sentiment-n2` | `#f4836b` | `#d9634c` | Negative (-0.6 to -0.3). |
| `dataviz.sentiment.n1` | `--sentiment-n1` | `#d6a596` | `#b98a7d` | Slightly negative (-0.3 to -0.1). |
| `dataviz.sentiment.neutral` | `--sentiment-neutral` | `#8c9aa6` | `#7d8b96` | Neutral (-0.1 to 0.1). |
| `dataviz.sentiment.p1` | `--sentiment-p1` | `#93c9b8` | `#6fa696` | Slightly positive (0.1 to 0.3). |
| `dataviz.sentiment.p2` | `--sentiment-p2` | `#4fd6ad` | `#2a9f7c` | Positive (0.3 to 0.6). |
| `dataviz.sentiment.p3` | `--sentiment-p3` | `#14e3a0` | `#0b7f5c` | Strongly positive (>= 0.6). |

Binning: `n3` <= -0.6 < `n2` <= -0.3 < `n1` <= -0.1 < `neutral` < 0.1 <= `p1` < 0.3 <= `p2` < 0.6 <= `p3`. Always print the signed score (e.g. `-0.42`) next to the colour; colour is never the only channel.

### Topics (categorical)

Same hue families as the current TOPIC_COLORS, so returning users keep their bearings, with one change: Technology moves from cyan to azure so cyan is free to mean "selected". Values are slightly desaturated for small, dense marks.

| Token | CSS var | Dark | Light | Use |
|---|---|---|---|---|
| `dataviz.topic.all` | `--topic-all` | `#9ab0c1` | `#3d5466` | No topic filter. |
| `dataviz.topic.politics` | `--topic-politics` | `#9b8cff` | `#6550e0` | Politics. |
| `dataviz.topic.conflict` | `--topic-conflict` | `#ff6464` | `#d23b3b` | Conflict. |
| `dataviz.topic.technology` | `--topic-technology` | `#4ea8ff` | `#1f6fd1` | Technology (was #06B6D4). |
| `dataviz.topic.climate` | `--topic-climate` | `#3fcf8e` | `#178a5a` | Climate. |
| `dataviz.topic.economy` | `--topic-economy` | `#f2b33d` | `#a86d00` | Economy. |
| `dataviz.topic.health` | `--topic-health` | `#f075b6` | `#c2427f` | Health. |

## Typography

A compact scale built on 13px. Headlines never exceed 15px inside panels; hierarchy comes from weight and colour, which keeps the desk dense without shouting.

| Font role | Stack | Use |
|---|---|---|
| `font.family.brand` (`--font-brand`) | Orbitron, sans-serif | Wordmark only. |
| `font.family.heading` (`--font-heading`) | Space Grotesk, system-ui, sans-serif | Panel titles, headlines, UI labels. |
| `font.family.body` (`--font-body`) | Space Grotesk, system-ui, sans-serif | Prose: co-pilot answers, AI summaries. |
| `font.family.mono` (`--font-mono`) | JetBrains Mono, ui-monospace, monospace | Every number, timestamp, coordinate and keyboard hint. |

| Style | Family | Size / line | Weight | Tracking | Use |
|---|---|---|---|---|---|
| `typography.title` | Space Grotesk | 15/20 | 600 | -0.005em | Preview headline, focused story title. |
| `typography.heading` | Space Grotesk | 13/18 | 600 | 0 | Panel titles. |
| `typography.body` | Space Grotesk | 13/20 | 400 | 0 | Co-pilot answers, AI summaries. |
| `typography.bodySm` | Space Grotesk | 12/17 | 400 | 0 | Row headlines, secondary prose. |
| `typography.label` | Space Grotesk | 11/14 | 500 | 0.01em | Column headers, control labels (sentence case). |
| `typography.dataLg` | JetBrains Mono | 16/20 | 500 | 0 | Header readouts (clock, totals). Uses `"tnum" 1, "zero" 1`. |
| `typography.data` | JetBrains Mono | 12/16 | 400 | 0 | Table values, scores, timestamps. Uses `"tnum" 1`. |
| `typography.dataSm` | JetBrains Mono | 10.5/14 | 400 | 0 | Axis ticks, keyboard hints. Uses `"tnum" 1`. |

CSS: each style is a `font` shorthand, e.g. `font: var(--type-title);`, plus `letter-spacing: var(--tracking-*)` where tracking is non-zero.

## Space, radii, borders

4px base grid. Panels use `space.3` (8px) inner gutters and `space.4` (12px) padding; rows are 32px tall in tables and 40px in the watchlist.

| Space | `0` | `1` | `2` | `3` | `4` | `5` | `6` | `7` | `8` |
|---|---|---|---|---|---|---|---|---|---|
| px | 0 | 2 | 4 | 8 | 12 | 16 | 20 | 24 | 32 |

Near-square. Radius signals "this is a control": panels get 4px, chips 3px, nothing is pill-shaped except status dots.

| Radius | Value | Use |
|---|---|---|
| `radius.none` | 0px | Chart plots, table cells. |
| `radius.xs` | 2px | Sparklines bars, inline bars. |
| `radius.sm` | 3px | Chips, buttons, inputs. |
| `radius.md` | 4px | Panels, preview card. |
| `radius.round` | 999px | Status dots only. |

| Border width | Value | Use |
|---|---|---|
| `borderWidth.hairline` | 1px | All dividers and outlines. |
| `borderWidth.strong` | 2px | Selection bar, focus ring, active tab underline. |

## Elevation and glow

Panels sit flat on the canvas (no shadow). Only things that float over the globe get a shadow, and there is no glow anywhere except the frozen brand lockup.

| Token | Dark | Light | Use |
|---|---|---|---|
| `elevation.flat` | `none` | `none` | Panels. |
| `elevation.float` | `0px 8px 24px 0px rgba(0, 0, 0, 0.45), 0px 0px 0px 1px rgba(34, 49, 62, 1)` | `0px 8px 24px 0px rgba(15, 28, 38, 0.12), 0px 0px 0px 1px rgba(207, 216, 224, 1)` | Hover preview, menus. |

## Motion

Short and functional. Nothing loops. With `prefers-reduced-motion: reduce`, durations drop to 0 and fly-to becomes a cut.

| Token | CSS var | Value | Use |
|---|---|---|---|
| `motion.duration.instant` | `--dur-instant` | `80ms` | Hover colour changes. |
| `motion.duration.fast` | `--dur-fast` | `120ms` | Preview card appear, chip toggle. |
| `motion.duration.base` | `--dur-base` | `180ms` | Panel content swap, brush snap. |
| `motion.duration.flyTo` | `--dur-fly-to` | `1000ms` | Globe camera move to a location. |
| `motion.easing.standard` | `--ease-standard` | `cubic-bezier(0.2, 0, 0, 1)` | Default for UI transitions. |
| `motion.easing.exit` | `--ease-exit` | `cubic-bezier(0.4, 0, 1, 1)` | Dismissals. |
| `motion.easing.camera` | `--ease-camera` | `cubic-bezier(0.65, 0, 0.35, 1)` | Globe fly-to (ease in-out). |

## Component patterns

### Panel

Opaque rectangle docked to the grid. 28px header strip in `surface.raised` with the title or tabs on the left and actions on the right; the body scrolls on its own.

| Property | Token / value |
|---|---|
| `component.panel.background` | `{color.surface.panel}` |
| `component.panel.headerBackground` | `{color.surface.raised}` |
| `component.panel.border` | `{color.border.default}` |
| `component.panel.radius` | `{radius.md}` |
| `component.panel.headerHeight` | `28px` |
| `component.panel.padding` | `{space.4}` |
| `component.panel.title` | `{typography.heading}` |

### Row (threads, places, entities, tables)

Thread rows are two lines (title and count; status, country codes and a 7-day tone sparkline). Place and entity rows are 40px tables with mono numbers right-aligned. Selected rows get `surface.selected` and a 2px cyan leading bar.

| Property | Token / value |
|---|---|
| `component.row.height` | `40px` |
| `component.row.heightCompact` | `32px` |
| `component.row.divider` | `{color.border.subtle}` |
| `component.row.hover` | `{color.surface.hover}` |
| `component.row.selected` | `{color.surface.selected}` |
| `component.row.selectedBar` | `{color.accent.primary}` |

### Chip and topic tab

24px, 3px radius. Topic tabs carry an 8px colour square, a mono count and a number key (1 to 7); the active tab gets a cyan underline rather than a fill, so topic colour and selection never compete. Entity chips open the entity tracker.

| Property | Token / value |
|---|---|
| `component.chip.height` | `24px` |
| `component.chip.paddingX` | `{space.3}` |
| `component.chip.radius` | `{radius.sm}` |
| `component.chip.border` | `{color.border.default}` |
| `component.chip.activeFill` | `{color.accent.soft}` |
| `component.chip.activeIndicator` | `{color.accent.primary}` |
| `component.chip.label` | `{typography.label}` |

### Readout

Label over value: label in `typography.label`, value in `typography.dataLg`. Used in the masthead (UTC, stories, places, feed) and the inspector stat strip.

| Property | Token / value |
|---|---|
| `component.readout.label` | `{typography.label}` |
| `component.readout.labelColor` | `{color.text.muted}` |
| `component.readout.value` | `{typography.dataLg}` |
| `component.readout.valueColor` | `{color.text.primary}` |

### Hover recon card

320px card beside the hovered place, joined by a 1px elbow leader to an 8px square marker. Order: 16:9 thumbnail at 40% width plus place, count and 24-bar sparkline; two-line headline with source and age; topic-mix bar with its top three topics; tone meter with signed score; up to three entity chips; two-line AI brief tagged AI; footer hints (click to open, P to pin, link count). Image states: photo, publisher logo (name on a plain tile), no image (topic glyph), conflict photo (blurred with a Show button).

| Property | Token / value |
|---|---|
| `component.preview.width` | `320px` |
| `component.preview.background` | `{color.surface.overlay}` |
| `component.preview.radius` | `{radius.md}` |
| `component.preview.shadow` | `{elevation.float}` |
| `component.preview.leader` | `{color.accent.primary}` |
| `component.preview.thumbShare` | `40%` |
| `component.preview.enter` | `{motion.duration.fast}` |

### Tone meter

8px bar with the seven sentiment stops as a gradient, a hairline at zero and a 4px marker at the value; the signed score is printed to its right.

| Property | Token / value |
|---|---|
| `component.toneMeter.height` | `8px` |
| `component.toneMeter.marker` | `{color.text.primary}` |
| `component.toneMeter.zero` | `{color.bg.inset}` |
| `component.toneMeter.score` | `{typography.data}` |

### Topic-mix bar

8px stacked bar, 1px gaps, segments in topic order with width = share; the top three topics are listed beneath with percentages.

| Property | Token / value |
|---|---|
| `component.topicMix.height` | `8px` |
| `component.topicMix.gap` | `1px` |
| `component.topicMix.legend` | `{typography.dataSm}` |

### Inspector (link, entity, place)

Top of the right column. Link: A and B, a four-cell stat strip (stories, lift, topic, tone), shared entities and themes, linking stories, and an Explain this link button tagged AI. Entity: totals, 7-day trend, top places with tone, co-mentions as chips ("appears in coverage with"). Place: AI briefing, lead story, linked places.

| Property | Token / value |
|---|---|
| `component.inspector.title` | `{typography.title}` |
| `component.inspector.statBorder` | `{color.border.subtle}` |
| `component.inspector.sectionLabel` | `{typography.label}` |

### Connection arc

Same-thread arcs use the thread's topic colour as a gradient that fades from the origin (direction without animation). Co-coverage arcs are neutral with width by story count. The inspected link is cyan. Arcs only animate (dash flow) during a replay the user started.

| Property | Token / value |
|---|---|
| `component.connection.stroke` | `0.35` |
| `component.connection.coverage` | `{color.arc.coverage}` |
| `component.connection.highlight` | `{color.arc.highlight}` |
| `component.connection.muted` | `{color.arc.muted}` |
| `component.connection.altitudeScale` | `0.32` |

### Thread panel and spread replay

Bottom tray: AI synopsis and facts on the left; in the middle a 7-day strip of hourly bars coloured by tone over one lane per place (diamond at first report, bar to now) with a cyan playhead, replay button and 1x/4x/16x speeds; key entities, reported figures and a quote on the right.

| Property | Token / value |
|---|---|
| `component.replay.laneHeight` | `15px` |
| `component.replay.marker` | `{dataviz.topic.economy}` |
| `component.replay.playhead` | `{color.accent.primary}` |
| `component.replay.axis` | `{typography.dataSm}` |

### Status rail (last visit and surges)

30px strip under the command bar: "Since your last visit" with counts, Replay what I missed and the two top developments on the left; a surge list (place, ratio in `signal.warning`, reason) on the right. Dismissible.

| Property | Token / value |
|---|---|
| `component.statusRail.height` | `30px` |
| `component.statusRail.surge` | `{color.signal.warning}` |
| `component.statusRail.text` | `{typography.bodySm}` |

### Co-pilot console

Right column, below the inspector. Context strip (what it sees), suggested questions, then messages without bubbles: speaker label, a collapsible tool trace, prose with bracketed citations, a source list, and a row of cyan action chips (fly to, show links, open thread, track entity, set window). Proactive callouts sit under the answer and never run on their own.

| Property | Token / value |
|---|---|
| `component.console.background` | `{color.surface.panel}` |
| `component.console.prose` | `{typography.body}` |
| `component.console.trace` | `{typography.dataSm}` |
| `component.console.traceColor` | `{color.text.muted}` |
| `component.console.citation` | `{color.accent.primary}` |
| `component.console.action` | `{color.accent.soft}` |
| `component.console.inputBackground` | `{color.bg.inset}` |

### Investigation board

Modal sheet over the desk: pins as flat 214px cards on a dotted field, auto edges typed by style (same thread cyan, shared entity grey, covered together dashed, close in time dotted, your own links white and labelled), an edge legend with toggles, and an analysis memo tagged AI on the right.

| Property | Token / value |
|---|---|
| `component.board.pinWidth` | `214px` |
| `component.board.field` | `{color.bg.inset}` |
| `component.board.sameThread` | `{color.accent.primary}` |
| `component.board.sharedEntity` | `{color.text.secondary}` |
| `component.board.user` | `{color.text.primary}` |

## Accessibility check (computed)

WCAG 2.x contrast ratios, generated from the token values (translucent surfaces composited over `bg.page`). Target: 4.5 for text, 3.0 for large text and non-text UI.

| Mode | Surface | Foreground | Ratio | Target | Result |
|---|---|---|---|---|---|
| dark | bg.page | text.primary | 15.71 | 4.5 | pass |
| dark | bg.page | text.secondary | 8.80 | 4.5 | pass |
| dark | bg.page | text.muted | 5.92 | 4.5 | pass |
| dark | bg.page | accent.primary (as text) | 11.16 | 4.5 | pass |
| dark | bg.page | border.strong (UI) | 3.95 | 3 | pass |
| dark | bg.page | sentiment.n3 (mark) | 6.42 | 3 | pass |
| dark | bg.page | sentiment.p3 (mark) | 11.78 | 3 | pass |
| dark | surface.panel | text.primary | 14.99 | 4.5 | pass |
| dark | surface.panel | text.secondary | 8.39 | 4.5 | pass |
| dark | surface.panel | text.muted | 5.64 | 4.5 | pass |
| dark | surface.panel | accent.primary (as text) | 10.64 | 4.5 | pass |
| dark | surface.panel | border.strong (UI) | 3.77 | 3 | pass |
| dark | surface.panel | sentiment.n3 (mark) | 6.12 | 3 | pass |
| dark | surface.panel | sentiment.p3 (mark) | 11.24 | 3 | pass |
| dark | surface.raised | text.primary | 13.99 | 4.5 | pass |
| dark | surface.raised | text.secondary | 7.84 | 4.5 | pass |
| dark | surface.raised | text.muted | 5.27 | 4.5 | pass |
| dark | surface.raised | accent.primary (as text) | 9.94 | 4.5 | pass |
| dark | surface.raised | border.strong (UI) | 3.52 | 3 | pass |
| dark | surface.raised | sentiment.n3 (mark) | 5.72 | 3 | pass |
| dark | surface.raised | sentiment.p3 (mark) | 10.49 | 3 | pass |
| light | bg.page | text.primary | 14.80 | 4.5 | pass |
| light | bg.page | text.secondary | 6.76 | 4.5 | pass |
| light | bg.page | text.muted | 4.94 | 4.5 | pass |
| light | bg.page | accent.primary (as text) | 4.99 | 4.5 | pass |
| light | bg.page | border.strong (UI) | 3.40 | 3 | pass |
| light | bg.page | sentiment.n3 (mark) | 4.73 | 3 | pass |
| light | bg.page | sentiment.p3 (mark) | 4.28 | 3 | pass |
| light | surface.panel | text.primary | 17.29 | 4.5 | pass |
| light | surface.panel | text.secondary | 7.90 | 4.5 | pass |
| light | surface.panel | text.muted | 5.77 | 4.5 | pass |
| light | surface.panel | accent.primary (as text) | 5.83 | 4.5 | pass |
| light | surface.panel | border.strong (UI) | 3.97 | 3 | pass |
| light | surface.panel | sentiment.n3 (mark) | 5.53 | 3 | pass |
| light | surface.panel | sentiment.p3 (mark) | 4.99 | 3 | pass |
| light | surface.raised | text.primary | 15.93 | 4.5 | pass |
| light | surface.raised | text.secondary | 7.28 | 4.5 | pass |
| light | surface.raised | text.muted | 5.32 | 4.5 | pass |
| light | surface.raised | accent.primary (as text) | 5.37 | 4.5 | pass |
| light | surface.raised | border.strong (UI) | 3.66 | 3 | pass |
| light | surface.raised | sentiment.n3 (mark) | 5.09 | 3 | pass |
| light | surface.raised | sentiment.p3 (mark) | 4.60 | 3 | pass |

## Mobile adaptation

- Below 1100px the bottom analysis tray collapses to tabs (Timeline / Entities / Links); below 760px the desk becomes a single column: globe on top (55vh), then a segmented control that swaps the watchlist, analysis tabs and co-pilot into one sheet.
- Topic tabs become a horizontal scroller; counts stay visible.
- The hover preview becomes a tap preview pinned to the bottom of the globe viewport (no leader line), with "Open" and "Ask co-pilot" as 44px targets.
- Keyboard hints are hidden on touch devices.

## Do and don't

- Do keep every panel opaque. If something must float over the globe, it uses `surface.overlay` plus `elevation.float`.
- Do right-align numbers in tables and keep them mono.
- Don't use cyan for a data series. Don't add glow.
- Don't auto-rotate the globe; offer a "Reset view" button instead.
