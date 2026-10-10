# Orbis UI revamp: design directions

**Date:** 2026-10-10
**Branch:** `claude/ui-revamp-exploration`
**Status:** Exploration only. These are mockups and token specs. No app code was changed, nothing was committed or deployed.
**Companion:** [`../features/feature-exploration.md`](../features/feature-exploration.md) (feature report). Every direction is designed around its section 6.

## Recommendation

**Build Soft Orbit**, with two things borrowed from Observatory: its Day theme roles (the app has a light mode today and Soft Orbit is dark-only) and its logbook layout for phones. Keep Signal Desk as the reference for information density, and don't take Orbital HUD forward.

Why Soft Orbit:

- **It matches the owner's latest brief most directly.** The brief asked for sci-fi mixed with soft, elegant UI. Soft Orbit has rounded frosted panels, cyan easing into periwinkle and lavender, orbital rings, and calm motion that can be switched off.
- **It keeps Signal Desk's features one-for-one.** The owner liked those features. Every Signal Desk surface has a place in Soft Orbit, and only three are open by default.
- **It's the cheapest soft option to build on the current code.** It keeps today's structure (full-bleed globe, floating panels, brand cyan), so `PanelQueue`, `AgentPanel`, `TimeSlider` and `TopicFilter` become restyled floating panels, not a new layout.

**Main risk:** `backdrop-filter` over a WebGL canvas. Ship it with the low-power fallback described under performance below.

Choose **Observatory** instead if the owner wants Orbis to feel more like an editorial product than a tool. It is more distinctive, has a real light theme, and uses blur in one place only. The cost is a bigger layout change (logbook column, off-centre globe) and more copywriting.

## How we got here

1. **First brief: "a sci-fi cockpit".** It should let you analyse and connect world events, with hover previews on cities, and develop reusable style themes. I explored three angles: dense mission control (Signal Desk), cinematic HUD (Orbital HUD) and tactical map table (Ops Table, never built).
2. **Feature report.** The feature agent's six priority surfaces and HUD elements were added to every direction.
3. **Owner feedback on Signal Desk.** The owner liked the features but said it "looks too much like a government website" and asked for "sci-fi mixed with soft, elegant UI". So the remaining work changed course:
   - **Soft Orbit:** the priority soft direction.
   - **Observatory:** a second soft variation that replaced Ops Table.
   - **Signal Desk:** stays as the dense reference.
   - **Orbital HUD:** already built before the feedback. Kept for comparison as the most cinematic, hardest-edged end of the range.

## The four directions

Open each `mockup.html` directly in a browser. They are self-contained except for Google Fonts and pinned CDN files (globe.gl 2.45.0 with an SRI hash, plus the three-globe country GeoJSON and textures).

| Direction | Pitch | Status | Files |
|---|---|---|---|
| **Soft Orbit** | Signal Desk's features in a calm, frosted cockpit. Rounded glass panels float over a drifting globe wrapped in orbital rings, with cyan easing into periwinkle and lavender. | **Recommended** | [mockup](./soft-orbit/mockup.html), [tokens.md](./soft-orbit/tokens.md), [tokens.json](./soft-orbit/tokens.json) |
| **Observatory** | A warm, cinematic night-and-day observatory. A large off-centre globe sits in a fine astrolabe ring, a narrative logbook runs beside it, and connections are drawn as constellations. | Soft alternative | [mockup](./observatory/mockup.html), [tokens.md](./observatory/tokens.md), [tokens.json](./observatory/tokens.json) |
| **Signal Desk** | A quiet, dense analyst's desk where the globe is one instrument among watchlists, trend lines and tables. | Dense reference (owner: too "government website") | [mockup](./signal-desk/mockup.html), [tokens.md](./signal-desk/tokens.md), [tokens.json](./signal-desk/tokens.json) |
| **Orbital HUD** | The globe is the cockpit window: a full-bleed holographic HUD with an instrument ring for topics and time, lock-on previews and flowing connection arcs. | Built before the feedback; not recommended | [mockup](./orbital-hud/mockup.html), [tokens.md](./orbital-hud/tokens.md), [tokens.json](./orbital-hud/tokens.json) |

What each one looks like at a glance:

- **Soft Orbit:**
  - deep warm-violet night sky with faint starfield and haze;
  - dotted periwinkle land on an indigo sphere;
  - two tilted orbital ellipses with satellites, and a ticked ring;
  - frosted panels with 20 to 28px radii and a cyan-to-lavender edge light;
  - pill controls everywhere;
  - a timeline "capsule" at the bottom with an aurora play button.
- **Observatory:**
  - warm ink sky in Night, cool porcelain in Day (deliberately not cream);
  - city lights on the night texture against a cool atmosphere rim;
  - hairline champagne astrolabe with graduations;
  - a logbook column of large light type;
  - a "time horizon" of hourly ticks under the globe;
  - the board as a star chart.
- **Signal Desk:**
  - opaque graphite panels on a 4px grid;
  - mono tabular numbers, with cyan used only for selection;
  - hex-dot globe with volume columns;
  - dark and light ("paper") themes.
- **Orbital HUD:**
  - night texture, plus a calibrated ring around the globe: the top arc holds the topic segments and the bottom arc is a 7-day radial histogram you scrub;
  - corner brackets on glass panels match the lock-on reticle;
  - dark only.

## Shared foundations (true of all four)

- **Brand lockup frozen.** The lockup is copied from `frontend/src/app/page.tsx` and is identical in all four:
  - logo PNG at 40px with `drop-shadow(0 0 12px rgba(0,212,255,.5))`;
  - "Orbis" in Orbitron 700, 18px, uppercase, 0.2em tracking, with its cyan text-shadow;
  - "Every Story, Everywhere" in system-ui 500, 9px, uppercase, 0.3em tracking, in the existing muted colour.

  The logo is the real asset, downscaled and embedded as a data URI. In Orbital HUD, Soft Orbit and Observatory it also sits at the same screen position as today. Orbitron is never used anywhere else.
- **One token vocabulary.** All four specs use the same role names, so a component built against one direction re-themes by swapping the token file:
  - colour roles: `bg.*`, `surface.*`, `border.*`, `text.*`, `accent.*`, `signal.*`, `globe.*`, `arc.*`, `dataviz.sentiment.*`, `dataviz.topic.*`;
  - typography roles, `space.*`, `radius.*`, `elevation.*`, and `motion.duration.*` / `motion.easing.*`.

  Each direction adds a few roles of its own (`orbit.*`, `chart.*`, `hud.*`, `edge`). CSS variable names reuse today's names where they exist (`--bg-page`, `--surface-panel`, `--text-primary`, `--border-subtle`), so migration starts as a value swap.
- **Format.**
  - `tokens.json`: W3C Design Tokens style, with `$value`, `$type`, `$description` and `{alias}` references.
  - Modes: dark is the `$value`; light lives in `$extensions["co.orbisapp"].modes.light`; CSS variable names are in `$extensions["co.orbisapp"].css`.
  - Each `tokens.md` holds the same values as tables, plus principles, component patterns, mobile notes and a computed WCAG contrast report.
  - One source generated each mockup's `:root` block, its `tokens.json` and its `tokens.md`, so the three can't drift.
- **Data viz.**
  - **Topics:** the hues users already know are kept, except Technology, which moves from cyan to azure or sky so that cyan only ever means brand or selection.
  - **Sentiment:** the 3-step red/amber/green becomes a 7-step diverging scale (red or rose, through grey, to teal). Its ends differ in lightness for colour-blind readers, and every value also prints its signed score.
- **Image states in the hover card:**
  - photo;
  - publisher logo (some `image_url`s will be logos, per the feature report);
  - no image: a topic glyph, or in Orbital HUD a crop of the night texture at that location;
  - conflict photo: blurred until the reader clicks Show.
- **Same sample world.** All four mockups show the same invented data and are labelled "Sample data":
  - 27 featured places and 55 minor ones;
  - 23 links and 5 threads;
  - an entity dossier for the Suez Canal Authority;
  - a co-pilot exchange about Lagos and the Red Sea rerouting.

## The six feature surfaces in each direction

From the feature report, section 6. "Default" means it is visible when the page loads. "On demand" means one click away (tab, arc, chip or button).

| Surface | Soft Orbit | Observatory | Signal Desk | Orbital HUD |
|---|---|---|---|---|
| **1. City hover card** (image or fallback, headline, topic mix, tone, 24 h sparkline, entities, AI brief, P to pin) | Default. Frosted card beside the place, curved leader from a soft circular reticle; clears both side panels | Default. The single floating card; champagne reticle and leader | Default. Opaque card with an elbow leader and square marker | Default. Card docked in the right column; leader runs from the bracket reticle across the globe |
| **2. Arcs and link inspector** | Default arcs (aurora for the active thread, faint for co-coverage). A pill on the inspected arc opens Inspect → link | Default arcs (champagne to cyan). Arc label opens the inspector card, which replaces the hover card | Default. Link inspector open at top right; arcs click through | Default arcs with flowing dashes; arc hover label; Link tab in the inspector |
| **3. Thread panel and spread replay** | Default (collapsed to the active thread and its route); expands for facts, entities, figures and a quote. Replay in the timeline capsule | Default as a logbook entry with a vertical spread log; replay on the time horizon | Default bottom tray: synopsis, tone-coloured hourly strip, one lane per place, playhead, speeds | Default left panel; replay drives the playhead on the ring's time dial |
| **4. Entity tracker** | On demand: Inspect → entity (constellation, top places with tone); globe draws arcs from the entity's centre of gravity | On demand: inspector card with a constellation chart | On demand: Entities tab plus inspector dossier; focus mode dims other places | Default: Entity tab with a co-mention network and top places |
| **5. Co-pilot with action chips** | Default right panel: context pills, answer with citation pills, action pills, proactive callout, pinned suggestions | Default: bottom of the logbook (sees line, answer, collapsed sources, action pills, callout) | Default: below the inspector, with tool trace and source list | Default: bottom-left; streams once at load |
| **6. Investigation board** | On demand: split view. Board sheet on the left, globe slides right and mirrors the pins | On demand: full-screen constellation chart with memo | On demand: modal with edge-type toggles and memo | On demand: overlay; Board tab lists pins |
| Layer switcher | Bottom-left pill: Dots / Intensity / Mood + Links / Threads | Top-right text tabs (same set) | Globe panel header (same set) | Top centre under search (same set) |
| Alert ticker (surges) | Bottom-right pill, crossfading every 6 s (static with reduced motion) | "Surging now" line in the logbook | Status rail, right side | Top right under the readouts; surge places pulse on the globe |
| Since-last-visit strip | Pill under the brand with Replay | First logbook entry with Replay | Status rail, left side | Strip under the brand, plus a "last visit" notch on the dial |
| Replay control | Aurora play button in the capsule | Round button at the left of the horizon | Thread tray transport with speeds | Transport under the ring, plus dial scrubbing (click or arrow keys) |
| Topic filter | Pill row, top centre (count on the active one) | Text tabs with a champagne underline | Command-bar tabs with counts and keys 1 to 7 | Top arc of the ring (focusable segments) |
| Time navigation | Smooth 7-day area chart with window band and last-visit mark; presets | Hourly tick horizon with window band; presets | Command-bar day stepper, presets and 168-bar mini histogram | Bottom arc of the ring: radial 7-day histogram |

**States not yet drawn.** The feature report asks panels to handle loading, empty, AI unavailable or paused, rate-limited (429), image missing, and expired (older than 7 days).

The mockups show some of these:

- the image states;
- "synopsis pending" when you pick a thread other than Red Sea;
- the copy "covered together, not cause and effect".

Recommended treatment for the rest, the same in every direction:

- **Loading:** skeleton rows in `surface.raised`.
- **Empty:** a sentence that suggests an action ("No stories here in this window. Try 24 h.").
- **AI paused or 429:** keep the non-AI data and replace the AI block with one line: "AI summaries are paused until 00:00 UTC" or "Too many requests. Try again in a minute". Never apologise.
- **Expired:** keep a snapshot of the title and source, labelled "No longer in the 7-day window".

## Comparison

| | Soft Orbit | Observatory | Signal Desk | Orbital HUD |
|---|---|---|---|---|
| Optimised for | Exploring and connecting, calmly; the owner's latest brief | Reading and presenting: the portfolio demo, briefings, screenshots | Scanning many numbers at once; power users | First impression, spectacle |
| Feel | Soft sci-fi, frosted, airy | Luxurious, cinematic, editorial | Instrument panel, dense, flat | Holographic, cinematic, hard-edged |
| Default density | Medium (3 surfaces open) | Low to medium (logbook + 1 card) | High (6 surfaces open) | Medium to high (5 panels plus the ring) |
| Themes | Dark only (borrow Observatory's Day roles) | Night and Day | Dark and light | Dark only |
| Globe | Hex-dot land, no texture, soft atmosphere | Night texture (Day: blue marble), cool rim | Hex-dot land, volume columns | Night texture, cyan atmosphere |
| Distinctive device | Aurora gradient, orbital rings | Logbook column, astrolabe, constellations | Watchlist tables, tone-coloured spread lanes | Instrument ring with radial time dial |
| Ambient motion | Drift ±5°, slow arc flow, satellites | Drift ±4°, slow arc flow | None (only on input) | Boot sequence, arc flow, surge pulses |
| Blur layers over the globe | 6 to 8 (panels, pills, card) | 1 to 2 (card, arc label) | 0 | 5 to 6 |
| Biggest risk | Blur cost on weak GPUs; too many pills | Layout departs most from today; copy-heavy | Owner already rejected the look | Hard-edged; ring geometry is fiddly on small screens |
| Mobile | Bottom sheet with a preview tab; globe above | Globe on top, logbook becomes the page | Single column, page scrolls | Bottom sheet with a preview tab; ring without labels |

## Implementation cost against the current codebase

Today the frontend has 9 components:

- **Globe:** `Globe.tsx` (globe.gl 2.45, night texture, points, rings, hex bins).
- **News panels:** `PanelQueue`, `NewsPanel` and `PanelTab`.
- **Agent:** `AgentPanel` and `AgentMessage`.
- **Controls:** `TimeSlider`, `TopicFilter` and `ThemeToggle`.

Theme variables are in `globals.css`.

**Work common to every direction:**

1. **Tokens.** Generate a CSS file from the chosen `tokens.json` and import it in `globals.css`. Then map the roles Tailwind needs in `@theme inline`, for example `--color-page: var(--bg-page)`, `--color-panel: var(--surface-glass)`, `--radius-panel: var(--radius-xl)`. The fonts are already exposed as `--font-brand`, `--font-heading` and `--font-mono` by `layout.tsx`, which matches the token names.
2. **Remove hard-coded colours.**
   - There are 83 Tailwind palette classes (mostly `blue-400`/`blue-500` in `NewsPanel`, `TimeSlider` and `AgentPanel`, plus `purple-500`, `emerald` and `amber`) and 84 hex or rgba literals across `components/`, `app/` and `lib/`.
   - `TOPIC_COLORS` and `getSentimentColor` in `lib/clustering.ts` move to tokens. The globe reads them at runtime with `getComputedStyle`, as the mockups do.
   - Fix in passing: `TimeSlider` uses `var(--surface-hover)`, which `globals.css` never defines.
3. **Globe.tsx.**
   - **Layer switcher:** points, `heatmapsData` and `hexBinPointsData`, toggled by state.
   - **Arcs:** `arcsData` with gradient colours, dash animation for the active thread, and `onArcClick` / `onArcHover`.
   - **Rings:** surges.
   - **Overlays:** a `getScreenCoords` loop that positions the hover card, reticle and place tags. Write positions to refs and styles, never React state, so nothing re-renders every frame.
   - **Material colour:** three-globe sets `material.color = null` once a texture loads. The current night-mode tint is therefore overwritten after load unless it is re-applied; the mockups guard for this.
4. **New components.** Hover card, link inspector, entity tracker, thread panel with replay, timeline, investigation board, layer switcher, surge ticker, since-last-visit strip.
   - `NewsPanel` becomes the place view in the inspector.
   - `AgentPanel` becomes the co-pilot console. Its action chips depend on the backend fix B1 (typed globe actions) in the feature report.
5. **Data.** The designs assume the feature report's endpoints:
   - `lead`, `topic_mix`, `avg_sentiment` and `image_url` on `/api/news`;
   - `/api/links`, `/api/threads/{id}/spread`, `/api/entities/...`, `/api/alerts` and `/api/news/delta`.

   Until those exist, the hover card can ship in its "Phase A" form: headline, count, tone and image fallback.

**Direction-specific cost** (relative, on top of the common work):

| Direction | Extra frontend work | Rough size |
|---|---|---|
| Soft Orbit | Glass panel shell with edge light (CSS mask), SVG orbital overlay with front and back masking, pill system, drift controller, split-view board (resize the globe canvas) | M |
| Observatory | New page layout (logbook column, off-centre globe by offsetting the canvas), astrolabe SVG, horizon chart, constellation renderer, Day theme with texture swap | M to L |
| Signal Desk | CSS grid desk, tables, hex-dot globe; least motion work | M |
| Orbital HUD | Ring geometry tied to camera altitude (recompute on zoom and resize), textPath topic segments, radial dial interaction, bracket glass | L |

## Performance risks (globe plus effects on low-end devices)

None of this was measured on real hardware. Treat it as risks to test, not results.

- **`backdrop-filter` over WebGL is the main risk** for Soft Orbit and Orbital HUD. Each blurred element re-samples the canvas behind it whenever the globe redraws, and globe.gl redraws every frame while anything animates.
  - Soft Orbit has the most blurred surfaces.
  - **Mitigation, already in the mockups:** a `low-power` class (set when `navigator.hardwareConcurrency <= 4`) swaps glass for solid fallbacks and stops arc flow and drift.
  - **For production, add:** `prefers-reduced-transparency`, a frame-time probe (drop blur if frames exceed about 24 ms), and fewer blurred layers. For example, blur only the large panels, and make pills semi-opaque instead.
- **Hex-dot land** (Soft Orbit, Signal Desk) builds many small meshes from 176 country polygons (Antarctica excluded). That is fine on desktop and may be heavy on mobile GPUs. Fallbacks: lower `hexPolygonResolution` on mobile, or bake the dots into a texture.
- **Textures.** The night texture is 715 KB; the blue marble used by Observatory's Day mode is 1.4 MB. Pin them, self-host them (today the app loads them unpinned from unpkg) and lazy-load the Day texture.
- **Arcs.** Dash animation is a cheap shader uniform, but keep the feature report's cap of 30 to 60 arcs. Thick or numerous arcs plus atmosphere plus blur add up.
- **Per-frame DOM work.** Anchored cards, reticles and tags are updated every frame in the mockups. In React, use one rAF loop that writes transforms to refs, and only for items facing the camera.
- **Ambient motion.** Drift and satellites keep the render loop busy. They stop under reduced motion, in low-power mode and on first interaction. The current app already auto-rotates, so the baseline cost is similar.

## Accessibility

- **Contrast.**
  - Every token set passes WCAG AA for text roles on its main surfaces, in both modes where they exist; each `tokens.md` lists the computed ratios.
  - Glass ratios are computed against the night sky. Over bright parts of the globe the glass is lighter, so dense text sits on a scrim.
  - **One frozen-brand issue:** the motto's existing colour is about 3.7:1 on the dark background and about 2.2:1 in light mode. It is below AA but was kept unchanged as instructed. Worth a decision from the owner.
- **Motion.** All mockups respect `prefers-reduced-motion`: no drift, boot animation or arc flow; fly-to becomes a cut; replay steps instead of tweening.
- **Keyboard.** Visible focus rings, `/` to search, Escape closes the board. Signal Desk adds 1 to 7 for topics and P to pin. Orbital HUD's ring segments and dial are focusable (Enter, arrow keys).
- **Colour is never the only channel.** Every sentiment colour prints a signed score, and topic dots carry labels.
- **Copy guards from the feature report.** "Covered together, not cause and effect", "appears in coverage with", "as reported", and AI content is always tagged.

## Mobile adaptation (summary)

Details are in each `tokens.md`. All four mockups were checked at 390×844 with no horizontal scroll.

- **Soft Orbit:**
  - panels become one bottom sheet with tabs (place preview, Threads, Co-pilot, Inspect);
  - the globe re-centres above the timeline capsule;
  - drift and blur are off.
- **Observatory:**
  - the globe moves to the top half and the logbook becomes the page;
  - the hover card becomes a compact tap card.
- **Signal Desk:** a single scrolling column (globe, thread tray, rail, inspector, co-pilot).
- **Orbital HUD:**
  - the globe and ring re-centre above a bottom sheet;
  - ring labels are hidden;
  - the preview moves into the sheet.

## What was and wasn't verified

**Verified:**

- **Desktop (1440×900):** all four mockups render with no console errors in headless Chromium (Playwright with software WebGL).
- **Other sizes:**
  - 390×844: all four;
  - 1100×800: Signal Desk, Soft Orbit and Observatory.

  Some layout fixes followed these checks.
- **Built-in browser:** Signal Desk was also checked in the app's built-in browser pane.
- **Interactions exercised:**
  - theme switches: Signal Desk light, Observatory Day;
  - layer switch to Mood;
  - entity tracking;
  - replay;
  - opening the board in each direction.
- **SRI:** the globe.gl hash matches both the CDN file and the installed npm package.

**Not verified:**

- Safari, Firefox and real phones.
- Frame rate on low-end GPUs.
- Screen-reader output beyond the semantic markup.
- Orbital HUD at 1100×800.
- The live site: I didn't visit https://orbisapp.co.
- The mockups need network access for Google Fonts and jsdelivr. Offline, they show a "globe needs WebGL and the globe.gl script" fallback and the panels still render.
- All headlines, figures and outlets attached to them are invented for design review. Each page shows a "Sample data" tag.
