# Soft Orbit Phase 2 (UI Foundation) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (or superpowers:executing-plans) to implement this plan task-by-task.

**Goal:** Move the Orbis frontend onto the Soft Orbit design (night sky, frosted glass, pills, dotted globe with orbital rings), with a layout that never overlaps, a 7-day timeline capsule and a co-pilot console.

**Architecture:**
- Tokens come verbatim from the approved mockup's generated `:root` block, with a test that keeps the two in sync.
- Layout is built from a small set of CSS primitives ported from the mockup (`.glass`, `.pill`, `.seg`, `.aurora-btn`, `.pillbar`). Each screen region is a CSS grid, so regions cannot overlap by construction, and a Playwright layout test asserts it at several viewport sizes.
- Each PR leaves the app fully working.

**Tech Stack:** Next.js 16 (App Router) + React 19, Tailwind v4 (`@theme inline`), globe.gl 2.45 / three-globe 2.45, framer-motion, Vitest + Testing Library, Playwright; FastAPI + asyncpg for the two small backend changes (PR 10, PR 11).

**Parent plan:** `docs/plans/2026-10-10-soft-orbit-redesign.md` (Phase 2 = PRs 8 to 11). Phase 1 is done and live (through #58).

**Design sources (read before starting):**
- `docs/redesign/ui/soft-orbit/tokens.md`: roles, typography, components, mobile rules, do and don't.
- `docs/redesign/ui/soft-orbit/mockup.html`:
  - lines 14–180: generated tokens;
  - lines 183–475: component CSS;
  - lines 1059–1069: starfield;
  - lines 1279–1344: globe and orbital rings.
- Design system artifact: https://claude.ai/artifact/MZ88T7Yogx1w4RsaiqgymQ

---

## Owner feedback this plan must fix (2026-10-11)

The owner approved the mockup and circled two layout problems:

1. **Top-right cluster is crowded.** The clock, Live, "Sample data" and Board pills are squeezed together and overlap. In the mockup the cluster and the centred search/topics column are positioned independently (`position: fixed` each), so at ~1440px they collide.
2. **Layer switcher collides with the timeline capsule.**
   - Cause: `.layers` is fixed at `left: 24px`, while `.timeline` is centred with `width: min(640px, 100vw - 800px)` and `min-width: 420px`. Between about 1180 and 1600px wide the two overlap.

**Fix by construction, not by tweaking offsets:**
- The top bar is one CSS grid (`1fr auto 1fr`).
- The bottom row is one CSS grid (`1fr minmax(0, 640px) 1fr`).
- Each region lives in its own track, so it can shrink or scroll but never sit on another.
- A Playwright layout test measures bounding boxes at 1024, 1280, 1440 and 1920px wide, and at 390px for phones. It fails if any two chrome regions overlap or sit closer than 12px.
- Phase 2 shows only controls that work. "Sample data" was mockup-only. Board arrives with PR 18, Search with PR 17, Threads with PR 16, and "since your last visit" and Surges with PR 14. The grids keep a slot for each.

## Working rules (every PR)

- Branch from `origin/main`, one branch per PR. **No stacked PRs:** #57 merged into its base branch instead of `main`.
- Frontend checks: `cd frontend && npm run lint && npm run test && npm run build`, then `npx prettier --check --end-of-line auto <changed files>` (on Windows plain `format:check` flags every file because of CRLF checkouts). Run e2e locally with `npx playwright test` (the config starts the dev server; the API is mocked in `e2e/fixtures.ts`).
- Backend checks (PR 10, 11): `cd backend && python -m pytest tests -q && python -m ruff check app && python -m ruff format --check app`.
- **Visual check before hand-off:**
  - Open the Vercel preview of the PR in the built-in browser at 1440×900, 1280×800, 1024×768 and 390×844.
  - Take screenshots, and compare against the mockup and the owner's two circled problems.
  - Put the 1440 screenshot in the PR description.
- Wait for all CI checks to be green before handing a PR to the owner.
- Never weight above 500, never all-caps labels (the brand motto is the exception), keep the brand lockup exactly as it is (tokens.md "Brand lockup (frozen)").

---

## PR 8: Soft Orbit tokens and fonts, dark only

Branch: `claude/p2-tokens`.

### Task 8.1: Token stylesheet with a drift test

**Files:**
- Create: `frontend/src/app/tokens.css`
- Create: `frontend/src/app/tokens.test.ts`

**Step 1: Write the failing test** (`frontend/src/app/tokens.test.ts`):

```ts
import { readFileSync } from "fs";
import path from "path";

// The mockup's :root block is generated from tokens.json; the app copies it verbatim.
const MOCKUP = path.resolve(__dirname, "../../../docs/redesign/ui/soft-orbit/mockup.html");
const TOKENS = path.resolve(__dirname, "./tokens.css");

function declarations(css: string): string[] {
  const start = css.indexOf("/* @tokens:start");
  const end = css.indexOf("/* @tokens:end */");
  const block = css.slice(start, end);
  return block
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l.startsWith("--") || l.startsWith("color-scheme"));
}

describe("Soft Orbit tokens", () => {
  it("match the approved mockup's generated :root block", () => {
    const fromMockup = declarations(readFileSync(MOCKUP, "utf8"));
    const fromApp = declarations(readFileSync(TOKENS, "utf8"));
    expect(fromMockup.length).toBeGreaterThan(150);
    expect(fromApp).toEqual(fromMockup);
  });
});
```

**Step 2:** Run `cd frontend && npx vitest run src/app/tokens.test.ts`. Expected: FAIL (`tokens.css` missing).

**Step 3:** Create `tokens.css`:
- Header comment: "Copied verbatim from docs/redesign/ui/soft-orbit/mockup.html (generated from tokens.json). Do not hand-edit; regenerate the mockup and copy again. tokens.test.ts checks they match."
- Then the mockup's lines 13–181 exactly (`/* @tokens:start … */`, the `:root { … }` block, `/* @tokens:end */`). Do not wrap it in `@layer`.

**Step 4:** Run the test. Expected: PASS.

**Step 5:** `git add frontend/src/app/tokens.css frontend/src/app/tokens.test.ts && git commit -m "feat(ui): add Soft Orbit tokens copied from the approved mockup"`.

### Task 8.2: Fonts feed the tokens

The tokens define `--font-brand/heading/body/mono` as plain family names ("Space Grotesk"…), but the app self-hosts fonts through `next/font/local`, which generates hashed family names. The `--type-*` shorthands are computed on `:root`, so the real font families must be available as variables on `<html>` itself.

**Files:**
- Modify: `frontend/src/app/layout.tsx`
- Modify: `frontend/src/app/globals.css`

**Steps:**
1. In `layout.tsx`, rename the three `variable:` options to `--font-orbitron`, `--font-space-grotesk` and `--font-jetbrains-mono`.
2. Move the three `.variable` classes from `<body>` to `<html>`: `<html lang="en" className={`${orbitron.variable} ${spaceGrotesk.variable} ${jetbrainsMono.variable}`}>`.
3. Remove the inline `style={{ fontFamily: … }}` from `<body>`.
4. In `globals.css`, import order is `@import "tailwindcss";` then `@import "./tokens.css";`. After the imports, add an unlayered override that points the token stacks at the self-hosted files:

```css
/* Self-hosted fonts (next/font on <html>) behind the token stacks. */
:root {
  --font-brand: var(--font-orbitron), Orbitron, sans-serif;
  --font-heading: var(--font-space-grotesk), "Space Grotesk", system-ui, sans-serif;
  --font-body: var(--font-space-grotesk), "Space Grotesk", system-ui, sans-serif;
  --font-mono: var(--font-jetbrains-mono), "JetBrains Mono", ui-monospace, monospace;
}
```

5. Add a vitest check (in `tokens.test.ts`) that `globals.css` contains each of the four lines above, so a later edit can't silently drop the self-hosted fonts.
6. Run the test, then `npm run build` (the brand wordmark must still render in Orbitron). Commit: `feat(ui): point the token font stacks at the self-hosted fonts`.

### Task 8.3: Replace the old theme block; aliases and Tailwind mapping

**Files:**
- Modify: `frontend/src/app/globals.css`

**Steps:**
1. Delete both old theme blocks (`:root, [data-theme="dark"] {…}` and `[data-theme="light"] {…}`). The tokens now define `--bg-page`, `--text-primary/secondary/muted` and `--border-subtle`.
2. Keep the old variable names that components still use as **aliases** until each component moves over. Remove an alias once nothing references it (`grep -r "var(--surface-panel)" src`).

```css
/* Aliases for pre-Soft-Orbit names; remove each once no component uses it. */
:root {
  --surface-panel: var(--surface-glass);
  --surface-card: var(--surface-raised);
  --surface-overlay: var(--surface-glass);
  --border-accent: var(--border-edge-a);
  --accent-cyan: var(--accent-primary);
  --text-motto: var(--brand-motto-color); /* #4482a8, AA 4.6:1 (PR #42) */
  --vignette: rgba(13, 12, 23, 0.7);
  --shadow: rgba(3, 2, 12, 0.55);
  --inset-highlight: rgba(255, 255, 255, 0.07);
}
```

3. Map tokens into Tailwind v4 so components can use utilities (`bg-glass`, `text-ink-2`, `border-line`):

```css
@theme inline {
  --color-page: var(--bg-page);
  --color-inset: var(--bg-inset);
  --color-glass: var(--surface-glass);
  --color-scrim: var(--surface-scrim);
  --color-raised: var(--surface-raised);
  --color-hover: var(--surface-hover);
  --color-selected: var(--surface-selected);
  --color-line: var(--border-subtle);
  --color-line-2: var(--border-default);
  --color-line-3: var(--border-strong);
  --color-ink: var(--text-primary);
  --color-ink-2: var(--text-secondary);
  --color-ink-3: var(--text-muted);
  --color-ink-inverse: var(--text-inverse);
  --color-accent: var(--accent-primary);
  --color-accent-strong: var(--accent-strong);
  --color-accent-soft: var(--accent-soft);
  --color-periwinkle: var(--accent-periwinkle);
  --color-lavender: var(--accent-lavender);
  --color-live: var(--signal-live);
  --color-warning: var(--signal-warning);
  --color-danger: var(--signal-danger);
  --color-background: var(--bg-page);
  --color-foreground: var(--text-primary);
}
```

4. Some token names coincide with Tailwind v4 theme variables: `--radius-sm/md/lg/xl`, `--font-mono`, `--ease-out` and `--ease-in-out`. Because `tokens.css` is unlayered, it overrides Tailwind's layered defaults. That is intended: `rounded-xl` (28px), `font-mono` and `ease-out` follow Soft Orbit. Say so in a comment above the `@theme` block.
5. Body:

```css
body {
  margin: 0;
  background:
    radial-gradient(1200px 800px at 12% 8%, var(--bg-haze-a), transparent 60%),
    radial-gradient(1100px 900px at 92% 96%, var(--bg-haze-b), transparent 60%),
    var(--bg-page);
  color: var(--text-primary);
  font: var(--type-body);
  overflow: hidden;
  -webkit-font-smoothing: antialiased;
}
:focus-visible {
  outline: var(--bw-focus) solid var(--border-focus);
  outline-offset: 3px;
}
```

6. Scrollbar thumb colours: `rgba(214, 218, 255, 0.18)` and `0.3` on hover. Delete `.scanlines`, `@keyframes scanline-sweep` and the `[data-theme="light"]` rules, after checking that nothing renders `scanlines` (`grep -rn scanlines src`).
7. Run `npm run build` and `npm run test`. Commit: `feat(ui): replace the theme block with Soft Orbit tokens and aliases`.

### Task 8.4: Retire the light theme

Soft Orbit is dark only (tokens.md "Modes").

**Files:**
- Delete: `frontend/src/components/ThemeToggle.tsx`, `frontend/src/lib/theme.tsx`, `frontend/e2e/theme.spec.ts`
- Modify: `frontend/src/app/layout.tsx`, `frontend/src/app/page.tsx`, `frontend/src/components/Globe.tsx`, `frontend/e2e/globe.spec.ts`

**Steps:**
1. `layout.tsx`: remove the theme `<script>` that reads `orbis-theme`, remove `ThemeProvider` and `suppressHydrationWarning` (keep it only if something else needs it), and drop `data-theme`. The tokens set `color-scheme: dark`.
2. `Globe.tsx`: remove `useTheme` and the effect that swaps textures by theme; keep the night texture until PR 9 restyles the globe.
3. `page.tsx`: remove `<ThemeToggle />`. The About link it carried moves to a temporary top-right link (`<a href="/about" className="pill" …>About</a>` at `fixed top-5 right-6`); PR 9 puts it into the top bar.
4. `e2e/globe.spec.ts`: delete the "theme toggle is present" test; keep "About link is visible" and make it pass. Move the "About link navigates to about page" test from `theme.spec.ts` into `globe.spec.ts`.
5. Check `src/app/about/page.tsx` renders on the new tokens (it uses the old variables via aliases). Fix any light-only class.
6. Run `npm run test`, `npm run build` and `npx playwright test`. Commit: `feat(ui): retire the light theme (Soft Orbit is dark only)`.

### Task 8.5: PR 8

1. Visual check on the Vercel preview. Today's UI should still render: same layout, new colours and fonts, no light theme, About link top-right.
2. Open the PR, titled `feat(ui): Soft Orbit tokens and fonts, dark only (PR 8)`.

---

## PR 9: Soft Orbit shell (sky, glass, pills, top bar, globe, orbital rings)

Branch: `claude/p2-shell`, from `main` after PR 8 merges.

### Task 9.1: CSS primitives

**Files:**
- Create: `frontend/src/app/soft-orbit.css` (imported from `globals.css` after `tokens.css`)
- Test: `frontend/src/app/tokens.test.ts` (extend)

**Steps:**
1. Port these rules verbatim from `mockup.html`: `.sr-only`, `.num`, `.muted`, `kbd` (lines 195–198); `.glass`, `.glass.edge::before`, `.low-power .glass…`, `.glass[hidden]`, `.ghead…`, `.gbody`, `.scrim` (222–247); the pill block `.pill` … `.seg button[aria-selected="true"]` (251–269); `.pillbar` (272); `.live` (284–285). Changes from the mockup:
   - `.glass` drops `position: fixed` and `z-index`. Placement belongs to the layout grids, not the primitive.
   - Add `@media (prefers-reduced-motion: reduce) { *, *::before, *::after { transition-duration: 0ms !important; animation: none !important; } }`, as in mockup line 473.
2. Add a test that `soft-orbit.css` defines `.glass`, `.pill`, `.seg`, `.aurora-btn`, `.pillbar` and `.low-power .glass`, so a refactor can't drop a primitive.
3. Commit: `feat(ui): port Soft Orbit glass, pill and segmented primitives`.

### Task 9.2: Motion preferences and low-power mode

**Files:**
- Create: `frontend/src/hooks/useMotionPrefs.ts`, `frontend/src/hooks/useMotionPrefs.test.ts`

**Behaviour:**
- `useMotionPrefs()` returns `{ reduced, lowPower }`.
- `reduced` follows `matchMedia("(prefers-reduced-motion: reduce)")` and updates on change.
- `lowPower` is true when `localStorage["orbis-low-power"] === "1"`, or when there's no override and `navigator.hardwareConcurrency <= 4`. Wrap storage access in try/catch.
- The hook toggles `low-power` on `document.documentElement`.

**TDD:**
- Mock `matchMedia` and `hardwareConcurrency`.
- Test the four combinations, the storage override, and that the class is set and removed.

Commit: `feat(ui): motion preferences and low-power mode`.

### Task 9.3: Sky (starfield)

**Files:**
- Create: `frontend/src/components/Sky.tsx`, `frontend/src/components/Sky.test.tsx`

**Steps:**
1. Port the static starfield from mockup lines 1059–1069 into a fixed `<canvas aria-hidden="true">` at `z-index: var(--z-sky)` with `pointer-events: none`.
2. Draw once on mount and on resize, debounced 150 ms. Use a seeded PRNG so stars don't jump on resize, and colour `--bg-star`.
3. Test that it renders a canvas with `aria-hidden` (jsdom has no 2D context, so guard `getContext` returning null).
4. Mount `<Sky />` first in `page.tsx`. The body already paints the two haze gradients.
5. Commit: `feat(ui): static starfield sky`.

### Task 9.4: Top bar: one grid, no overlap

**Files:**
- Create: `frontend/src/components/TopBar.tsx`, `frontend/src/components/StatusPill.tsx`, `frontend/src/components/StatusPill.test.tsx`
- Modify: `frontend/src/components/TopicFilter.tsx` (restyle), `frontend/src/app/page.tsx`, `frontend/src/app/soft-orbit.css`

**Layout CSS** (add to `soft-orbit.css`):

```css
/* Top bar: three tracks, so the brand, topics and status can never overlap. */
.topbar {
  position: fixed; top: 18px; left: 24px; right: 24px; z-index: var(--z-panel);
  display: grid; grid-template-columns: 1fr auto 1fr; align-items: start; gap: 24px;
  pointer-events: none; /* the globe stays draggable between controls */
}
.topbar > * { pointer-events: auto; min-width: 0; }
.topbar-left { justify-self: start; }
.topbar-center { justify-self: center; max-width: 100%; display: flex; flex-direction: column; align-items: center; gap: 10px; }
.topbar-right { justify-self: end; display: flex; align-items: center; gap: 10px; }
.topics { padding: 4px; gap: 2px; max-width: 100%; overflow-x: auto; scrollbar-width: none; }
.topics .pill { border-color: transparent; height: 28px; flex: none; }
@media (max-width: 1180px) { .status .lbl { display: none; } }
@media (max-width: 760px) {
  .topbar { grid-template-columns: 1fr auto; row-gap: 12px; left: 12px; right: 12px; top: 12px; }
  .topbar-center { grid-column: 1 / -1; grid-row: 2; justify-self: stretch; }
}
@media (max-width: 639px) { .status .clock { display: none; } }
```

**Components:**
- **`TopBar`**: `<header className="topbar">` with three slots.
  - Left: the brand lockup moved unchanged from `page.tsx` (same classes and inline styles). Keep `fixed`-free markup; the grid places it.
  - Centre: `<TopicFilter>`.
  - Right: `<StatusPill>` and the About pill.
- **`TopicFilter`**: one `<nav className="pillbar topics" aria-label="Topic filter" data-testid="topic-filter">` of `<button className="pill" aria-pressed>` with a 7px dot coloured `var(--topic-*)`. Keep the existing topic list and the `onTopicChange` contract.
- **`StatusPill`**: `<div className="pillbar status">` with:
  - the clock: `HH:MM` UTC, `.num`-styled at `--type-data-lg`, updated every 30 s, with `<span className="lbl">UTC</span>`;
  - one state: `Live` (`.live`), `Loading…` (muted) or `Offline` (`--signal-danger`), from props `{ isLive, isLoading, isOffline }`.
  - Tests: the time formats in UTC (fake timers), and each state renders its label.
- **`page.tsx`**: replace the inline branding block and the temporary About link with `<TopBar …/>`. `TimeSlider` keeps its own status until PR 10.

Commit: `feat(ui): top bar grid with topics and status`.

### Task 9.5: Globe restyle (dotted land, night ocean, drift)

**Files:**
- Create: `frontend/public/geo/ne_110m_admin_0_countries.geojson`, copied from `node_modules/three-globe/example/country-polygons/` (Natural Earth, public domain; add a one-line `frontend/public/geo/README.md` with source and licence).
- Modify: `frontend/src/components/Globe.tsx`, `frontend/src/lib/clustering.ts`, `frontend/src/lib/clustering.test.ts`
- Delete: `frontend/public/textures/` if nothing references it (`grep -rn textures src`).

**Steps:**
1. **Topic colours** read the tokens. In `clustering.ts`, `TOPIC_COLORS` becomes the pastel token values (`#c0c3e0` All, `#ab9dff` Politics, `#ff8f9c` Conflict, `#7db9ff` Technology, `#72ddb2` Climate, `#f4c97c` Economy, `#f5a0d0` Health). Add a test that these equal the `--topic-*` values in `tokens.css`, parsed from the file, so the canvas colours can't drift from the CSS.
2. **Globe** (port mockup lines 1283–1300):
   - `globeImageUrl(null)`, no bump map.
   - `globeMaterial()`: colour `--globe-ocean`, emissive `#1a1640`, intensity 0.35, shininess 8.
   - Atmosphere `--globe-atmosphere`, altitude 0.24.
   - `hexPolygonsData` from `fetch("/geo/ne_110m_admin_0_countries.geojson")`, without Antarctica (`ISO_A2 !== "AQ"`), using `hexPolygonResolution(3)`, `hexPolygonMargin(0.42)`, `hexPolygonUseDots(true)`, `hexPolygonAltitude(0.003)` and colour `rgba(111,120,201,0.55)`.
   - On fetch failure, log once and keep the plain ocean sphere.
   - Read token values once with `getComputedStyle(document.documentElement)`.
3. **Motion:** replace `autoRotate` with the calm drift from mockup lines 1349–1353: ±5° longitude over `--dur-drift`, 40 s.
   - The drift stops for good on the first `pointerdown` or `wheel` on the globe, and never starts when `reduced || lowPower` (`useMotionPrefs`).
   - Keep the existing point radius logic, rings and click handler.
4. **Expose geometry for the rings:** add `getGeometry(): { cx, cy, R } | null` to the controls passed to `onReady`, computed as in mockup lines 1314–1318.
5. `npm run test` and `npm run build`. Commit: `feat(ui): dotted Soft Orbit globe with calm drift`.

### Task 9.6: Orbital rings

**Files:**
- Create: `frontend/src/components/OrbitRings.tsx`, `frontend/src/components/OrbitRings.test.tsx`

**Steps:**
1. Port `renderOrbits` (mockup lines 1320–1344) into a fixed full-screen `<svg aria-hidden="true">` at `z-index: var(--z-orbit)`, with `pointer-events: none`.
2. It draws:
   - the dashed 1.08R circle with ticks every 15°, longer every 90°;
   - two tilted ellipses with a "behind the globe" mask;
   - satellites (`animateMotion`), only when `!reduced && !lowPower`.
3. It re-renders on a `requestAnimationFrame` loop only when `getGeometry()` changes, rounded to the pixel (the mockup's `orbitKey`).
4. Test that, with a stub geometry, it renders 24 tick lines and two ellipse groups, and no `animateMotion` when `reduced` is true.
5. Mount in `page.tsx` right after `<Globe>`.
6. Commit: `feat(ui): orbital rings around the globe`.

### Task 9.7: Layout test (no overlaps)

**Files:**
- Create: `frontend/e2e/layout.spec.ts`

```ts
import { test, expect, type Page } from "@playwright/test";
import { mockApi } from "./fixtures";

const SIZES = [
  { width: 1920, height: 1080 },
  { width: 1440, height: 900 },
  { width: 1280, height: 800 },
  { width: 1024, height: 768 },
  { width: 390, height: 844 },
];

// Chrome regions that must never touch. Later PRs add their regions here.
const REGIONS = ["brand", "topic-filter", "status-pill"];

async function boxes(page: Page) {
  const out: { id: string; x: number; y: number; w: number; h: number }[] = [];
  for (const id of REGIONS) {
    const el = page.getByTestId(id);
    if (!(await el.isVisible())) continue;
    const b = await el.boundingBox();
    if (b) out.push({ id, x: b.x, y: b.y, w: b.width, h: b.height });
  }
  return out;
}

const GAP = 12;
function tooClose(a: { x: number; y: number; w: number; h: number }, b: typeof a) {
  return !(
    a.x + a.w + GAP <= b.x ||
    b.x + b.w + GAP <= a.x ||
    a.y + a.h + GAP <= b.y ||
    b.y + b.h + GAP <= a.y
  );
}

for (const size of SIZES) {
  test(`chrome regions keep ${GAP}px apart at ${size.width}x${size.height}`, async ({ page }) => {
    await page.setViewportSize(size);
    await mockApi(page);
    await page.goto("/");
    await page.getByTestId("topic-filter").waitFor();
    const b = await boxes(page);
    for (let i = 0; i < b.length; i++)
      for (let j = i + 1; j < b.length; j++)
        expect(tooClose(b[i], b[j]), `${b[i].id} vs ${b[j].id}`).toBe(false);
    // Nothing is cut off by the viewport edge.
    for (const r of b) {
      expect(r.x).toBeGreaterThanOrEqual(0);
      expect(r.x + r.w).toBeLessThanOrEqual(size.width);
    }
  });
}
```

Notes:
- Add `data-testid="brand"` to the lockup and `data-testid="status-pill"` to `StatusPill`.
- Use the existing fixture helper name from `e2e/fixtures.ts`.
- Check that the test fails if you temporarily give `.topbar-right` a huge `width`, then revert.

Commit: `test(ui): layout spec keeps top-bar regions apart`.

### Task 9.8: PR 9

1. Run all checks and the visual check at the four sizes.
2. Open the PR `feat(ui): Soft Orbit shell (PR 9)`. Its description includes the 1440 screenshot and the layout-test sizes.

---

## PR 9b: Side panel (Co-pilot | Inspect) and narrow-screen sheet

Branch: `claude/p2-side`.

Today the stories panel (`PanelQueue` + `NewsPanel`, right edge, full height) and the agent panel (`AgentPanel`, left edge, full height, toggled by a round button) cover the globe. Soft Orbit puts both in one right-hand glass panel with tabs (mockup `.side`, lines 330–356). The co-pilot is open by default on wide screens (tokens.md principle 2).

### Task 9b.1: SidePanel container

**Files:**
- Create: `frontend/src/components/SidePanel.tsx`, `frontend/src/components/SidePanel.test.tsx`
- Modify: `frontend/src/app/soft-orbit.css`, `frontend/src/app/page.tsx`

**Behaviour:**
- `<section className="glass side" aria-label="Co-pilot and stories" data-testid="side-panel">` contains:
  - a `.ghead` with a `.seg` tablist: `Co-pilot` / `Stories`. Use "Stories" rather than the mockup's "Inspect": in Phase 2 the tab shows a place's stories, and PR 13/17 can rename it when links and entities arrive.
  - a collapse `iconbtn`;
  - the active tab's content in `.gbody`.
- Props: `{ tab, onTabChange, open, onOpenChange, copilot: ReactNode, stories: ReactNode, storiesCount?: number }`.
- When collapsed it renders a `pillbar` button "Co-pilot" (plus a stories count badge if any) at the same top-right anchor.
- Placement CSS: `.side { position: fixed; top: 96px; right: 24px; bottom: 124px; width: 380px; z-index: var(--z-panel); }`. The bottom value clears the timeline row reserved in PR 10.
- **State in `page.tsx`:** `sideTab` ("copilot" | "stories"), default "copilot"; `sideOpen`, default `window.innerWidth >= 1180` (read after mount to avoid a hydration mismatch).
- Clicking a dot opens the panel on "Stories".
- **Tests:**
  - The tabs switch content.
  - The `aria-selected` state.
  - Collapse renders the pill and expand restores it.
  - The keyboard: left and right arrows move between tabs.

### Task 9b.2: Stories tab (restyle NewsPanel, replace the queue)

**Files:**
- Modify: `frontend/src/components/NewsPanel.tsx`
- Create: `frontend/src/components/RecentPlaces.tsx`, `frontend/src/components/RecentPlaces.test.tsx`
- Delete: `frontend/src/components/PanelQueue.tsx`, `frontend/src/components/PanelTab.tsx`

**Steps:**
1. Give `NewsPanel` an embedded layout:
   - Remove its own `fixed` container, backdrop and slide animation; it renders inside `.gbody`.
   - Restyle with tokens (mockup `.insp`, `.art`, `.scrim`, `.ai`, `.pill`):
     - the place name in `--type-title`, with the count in `--type-label` muted;
     - the AI summary on a `.scrim` with the `AI` badge;
     - filters as pills; articles as `.art` rows (headline `--type-body-sm`; source and time muted);
     - sentiment as the `.sent` dot with the signed score, binned by tokens.md "Sentiment";
     - "Load more" as a `.pill`.
   - Keep `data-testid="news-panel"` and every existing behaviour: filters, selection summary, load more, minimise and close.
2. **`RecentPlaces`:** a row of up to 5 pills, one per open place (the old queue entries, `MAX_PANELS`). Clicking selects one, `×` closes it, and the active one is `aria-pressed`. It replaces `PanelQueue`/`PanelTab`; the queue state in `page.tsx` stays as it is.
3. Update `e2e/news-panel.spec.ts` for the new location. Clicking a point opens the side panel on Stories and shows `news-panel` inside `side-panel`.

### Task 9b.3: Co-pilot tab (container only)

**Files:**
- Modify: `frontend/src/components/AgentPanel.tsx`, `frontend/src/app/page.tsx`, `frontend/e2e/agent.spec.ts`

**Steps:**
1. Remove `AgentPanel`'s fixed full-height container, its own header close button and the separate round toggle in `page.tsx`; it renders inside the Co-pilot tab. Keep `data-testid`s `agent-panel` and `agent-input`.
2. Full restyle is PR 11. Here, make only the container blend in: transparent background, tokens for text.
3. Update `agent.spec.ts`: "agent toggle" becomes the Co-pilot tab, and "minimize" becomes the collapse button.

### Task 9b.4: Narrow screens (< 1180px): bottom sheet

**Files:**
- Modify: `frontend/src/app/soft-orbit.css`, `frontend/src/components/SidePanel.tsx`

**Steps:**
1. Below 1180px the side panel becomes a sheet:
   - `left: 12px; right: 12px; bottom: 12px; top: auto`;
   - `height: 46vh` open, or a 56px tab bar collapsed;
   - radius `--radius-xl`, as in mockup lines 442–454.
2. The timeline row (PR 10) sits above it. Until then, `TimeSlider` gets `bottom: calc(var(--sheet-h) + 24px)` through a CSS variable set by the sheet.
3. Extend `layout.spec.ts`: add the `side-panel` region at 1920, 1440 and 1280. At 1024 and 390 the sheet must not overlap `topic-filter` or `status-pill`.

### Task 9b.5: PR 9b

1. Run all checks and the visual check.
2. Open the PR `feat(ui): side panel with co-pilot and stories tabs (PR 9b)`.

---

## PR 10: Timeline capsule and layer switcher

Branch: `claude/p2-timeline`.

### Task 10.1: Backend: hourly volume for N days

**Files:**
- Modify: `backend/app/services/database.py`, `backend/app/routers/news.py`, `backend/app/models/news.py`
- Test: `backend/tests/test_database.py`, `backend/tests/test_news_router.py`

**Endpoint:** `GET /api/news/volume?days=7` (`days`: 1–7, default 7) returns `[{ "hour": "2026-10-11T14:00:00Z", "count": 31 }, …]`.
- It covers every hour from `date_trunc('hour', now() - days)` to the current hour, zeros included, oldest first.
- Cache key `db:volume:{days}`, TTL `settings.db_cache_ttl`.

**SQL** (in `database.get_hourly_volume(days)`):

```sql
SELECT h.hour, COALESCE(c.count, 0)::int AS count
FROM generate_series(
       date_trunc('hour', now() - make_interval(days => $1)),
       date_trunc('hour', now()),
       interval '1 hour') AS h(hour)
LEFT JOIN (
  SELECT date_trunc('hour', published_at) AS hour, count(*) AS count
  FROM articles
  WHERE published_at >= date_trunc('hour', now() - make_interval(days => $1))
  GROUP BY 1
) c USING (hour)
ORDER BY h.hour
```

**TDD:**
- The router validates `days` (0 and 8 give 422).
- It passes `days` to the query and serialises `hour` as ISO UTC.
- Zero hours are included (the mock returns them).
- Run the SQL against the local Postgres container if available (`docker ps`; see Phase 1 notes), and say so in the PR.

Keep `/api/news/density`: the old TimeSlider uses it until Task 10.6 removes it. Remove the endpoint in a later cleanup PR, once no client calls it.

Commit: `feat(api): hourly story volume for the timeline`.

### Task 10.2: Time window model

**Files:**
- Create: `frontend/src/lib/timeWindow.ts`, `frontend/src/lib/timeWindow.test.ts`
- Modify: `frontend/src/lib/panelQuery.ts` (+ test), `frontend/src/app/page.tsx`

```ts
export type LiveHours = 1 | 6 | 24 | 168;
export type TimeWindow =
  | { kind: "live"; hours: LiveHours }
  | { kind: "range"; startTime: string; endTime: string };

export const DEFAULT_WINDOW: TimeWindow = { kind: "live", hours: 24 };

/** Query params for /api/news and the cell endpoints. */
export function windowQuery(w: TimeWindow, now: number): {
  timespan: string; startTime?: string; endTime?: string;
} {
  if (w.kind === "range") return { timespan: "24h", startTime: w.startTime, endTime: w.endTime };
  return { timespan: `${w.hours}h` };
}

/** Concrete bounds, e.g. for panel queries frozen at click time. */
export function windowBounds(w: TimeWindow, now: number): { startTime: string; endTime: string } {
  if (w.kind === "range") return { startTime: w.startTime, endTime: w.endTime };
  return {
    startTime: new Date(now - w.hours * 3_600_000).toISOString(),
    endTime: new Date(now).toISOString(),
  };
}

export function windowLabel(w: TimeWindow): string; // "Last 6 h, live" | "Last 7 days, live" | "Tue 14:00 – Wed 02:00 UTC"
```

**TDD:**
- Each preset gives `timespan` `1h`, `6h`, `24h` and `168h`.
- Range passes through.
- Bounds for live use `now`.
- Labels for each preset and for a range across midnight are in UTC.

**Wiring:**
1. `page.tsx` replaces `dayOffset`, `timeRange`, `dayWindow` and `nowTs` with one `const [timeWindow, setTimeWindow] = useState<TimeWindow>(DEFAULT_WINDOW)`.
2. The globe fetch uses `windowQuery`.
3. `panelQuery(activeTopic, timeWindow, Date.now())` freezes `windowBounds` at click time. A live panel stays "live", but its bounds now use the preset's hours instead of `LIVE_WINDOW_HOURS`. Update `panelQuery.ts`, `samePanelQuery` (live panels match when topic and hours match) and their tests.
4. Check that the backend accepts `168h` (`_parse_timespan` returns the hours; `get_globe_points` uses them). If it caps the window, raise the cap to 168 and add a test.

Commit: `feat(ui): one time-window model for globe, panels and timeline`.

### Task 10.3: TimelineCapsule

**Files:**
- Create: `frontend/src/components/TimelineCapsule.tsx`, `frontend/src/components/TimelineCapsule.test.tsx`, `frontend/src/lib/volumeChart.ts`, `frontend/src/lib/volumeChart.test.ts`
- Modify: `frontend/src/lib/api.ts` (+ test): `fetchVolume(days)`
- Modify: `frontend/src/app/soft-orbit.css`: port `.timeline` (mockup 411–419) without `position`/`left`/`width` (the bottom row grid places it), plus `.aurora-btn` (259–260).

**`volumeChart.ts`** (pure, tested):
- `areaPath(points, width, height)` returns a smooth SVG path: monotone cubic, with no overshoot below 0.
- `xForTime(t, start, end, width)` and `timeForX(x, …)` snap to hours.
- `dayTicks(start, end)` returns the labels `Sun … Today`, in UTC.

**Component** (`<section className="pillbar timeline" data-testid="timeline">`), left to right:
1. **Replay button** (`.aurora-btn.play`, 56px), labelled "Replay the last 7 days" (see Task 10.4).
2. **Chart:**
   - An `<svg role="img" aria-label="Story volume over 7 days; …">` with the area (periwinkle gradient fill, aurora stroke), day labels, and the current window as a soft `--accent-soft` band with a playhead line.
   - Drag on the chart to select a range (snapped to whole hours, at least 1 h, within the 7 days). That sets `{ kind: "range" }`.
   - For keyboard users, two visually hidden `<input type="range">` (start and end hour index) mirror the band. Label them "Window start" and "Window end".
3. **Meta:**
   - the position label (`windowLabel`) in `--type-data`;
   - the story count `N stories · M places`, muted;
   - the presets `1h 6h 24h 7d` as `aria-pressed` buttons, where a preset sets `{ kind: "live", hours }`.

**Tests:**
- Presets call `onChange` with the right live window.
- Dragging from x1 to x2 gives a snapped range.
- Keyboard range inputs update the window.
- The label shows the current window.
- Replay is announced (Task 10.4).

The volume is fetched once on mount and every 15 minutes (ingestion cadence), cancelled on unmount.

### Task 10.4: Replay (7-day time-lapse)

Phase 2 replay steps through the last 7 days **day by day**. Thread-spread replay comes with PR 16.

**Behaviour:**
- Pressing play steps the window through `[d-7 … d-1, today]`, eight 24-hour ranges, every 1.6 s. Each step updates the globe through the normal fetch, so that's 8 requests, well under the 60/min data limit.
- Then it returns to the window active before replay.
- The playhead animates along the chart.
- Pressing again, choosing a preset or dragging the chart stops replay.
- With `reduced`, steps change instantly with no playhead animation.
- The button's `aria-label` switches to "Stop replay", and a polite live region announces each day ("Showing Tue").

**Implementation:**
- A `useReplay(steps, intervalMs)` hook in `frontend/src/hooks/useReplay.ts`, tested with fake timers: it starts, advances, stops on demand, restores the prior window and clears its interval on unmount.

### Task 10.5: Layer switcher (Dots, Intensity)

**Files:**
- Create: `frontend/src/components/LayerSwitcher.tsx` (+ test)
- Modify: `frontend/src/components/Globe.tsx`, `frontend/src/app/soft-orbit.css` (port `.layers`, `.tg`, `.sep` from mockup 405–410, without `position`)

**Behaviour:**
- `layers: { id: "dots" | "intensity"; label: string }[]` with a single active layer.
- Mood, Links and Threads are added by PRs 12, 13 and 16 when their data exists. Phase 2 shows only working layers.
- Intensity uses `heatmapsData([points])`: weight `count`, bandwidth 1.8, colour saturation 1.8, altitudes 0.006/0.04 (mockup line 1290). Dots hide while Intensity is on.
- `data-testid="layer-switcher"`; buttons are `aria-pressed`.
- Tests: the active state, and `onChange` on click.

### Task 10.6: Bottom row grid (fixes problem 2)

**Files:**
- Create: `frontend/src/components/BottomBar.tsx`
- Modify: `frontend/src/app/soft-orbit.css`, `frontend/src/app/page.tsx`
- Delete: `frontend/src/components/TimeSlider.tsx`, `frontend/e2e/time-slider.spec.ts`
- Create: `frontend/e2e/timeline.spec.ts`

```css
/* Bottom row: layers | timeline | (surges, PR 14). Tracks can't overlap. */
.bottombar {
  position: fixed; left: 24px; right: 24px; bottom: 20px; z-index: var(--z-panel);
  display: grid; grid-template-columns: 1fr minmax(0, 640px) 1fr; align-items: end; gap: 24px;
  pointer-events: none;
}
.bottombar > * { pointer-events: auto; min-width: 0; }
.bottombar .layers { justify-self: start; }
.bottombar .timeline { width: 100%; }
@media (max-width: 1180px) {
  /* stack: layers above the capsule, both centred; the sheet sits below */
  .bottombar { grid-template-columns: 1fr; justify-items: center; row-gap: 8px; bottom: calc(var(--sheet-h, 56px) + 24px); }
  .bottombar .layers { justify-self: center; }
}
@media (max-width: 760px) {
  .bottombar .layers { display: none; }
  .timeline .chart, .timeline .meta .pr { display: none; }
  .timeline { height: 64px; }
}
```

**Steps:**
1. In `page.tsx`, `<BottomBar>` contains `<LayerSwitcher>` and `<TimelineCapsule>`. Remove `TimeSlider`, `sliderRef`/`sliderHeight` and the `density` and `dayOffset` code.
2. In `e2e/fixtures.ts`, mock `/api/news/volume*`.
3. Write `timeline.spec.ts`:
   - the capsule is visible;
   - presets switch the label, and the globe re-fetches with `timespan=6h`;
   - replay starts and stops;
   - dragging the chart sets a range label.
4. Extend `layout.spec.ts` with the regions `timeline`, `layer-switcher` and `side-panel` (or the sheet) at all five sizes, and assert no overlap with each other or the top bar.

### Task 10.7: PR 10

1. Run all checks, including backend, and the visual check.
2. Open the PR `feat(ui): timeline capsule, 7-day volume and layer switcher (PR 10)`.

---

## PR 11: Co-pilot console

Branch: `claude/p2-copilot`.

### Task 11.1: Backend: screen context for the co-pilot

The co-pilot "sees your screen" (tokens.md Co-pilot). The frontend sends what is on screen; the backend uses it to scope retrieval.

**Files:**
- Modify: `backend/app/routers/agent.py`, `backend/app/services/agent.py`
- Test: `backend/tests/test_agent.py`, `backend/tests/test_agent_router.py` (or whichever file covers `AskRequest`)

**Request:** `AskRequest` gains `context: ScreenContext | None`:

```python
class ScreenContext(BaseModel):
    place: str | None = Field(None, max_length=100)    # cell's place name, e.g. "Madrid, Spain"
    topic: Literal["Politics", "Conflict", "Technology", "Climate", "Economy", "Health"] | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
```

**Rules:**
- `place` is user-controlled text that goes into a prompt. Clean it like `ai_summary._clean_place`: `sanitise_text`, one line, and dropped entirely if `has_injection_pattern`.
- Times must be within the last 7 days and ordered. Otherwise drop them; don't reject the question.
- The planner prompt gets one line, `Screen context: place=…; topic=…; window=… to … UTC`, only for the fields present.
- The planner's `keyword_search` defaults to that topic and window when the model omits them.
- Never send coordinates (Haiku narrates them; see Phase 1 notes).
- Cache and rate-limit behaviour are unchanged.

**TDD:**
- The context line appears with clean values.
- An injection or newline in `place` is cleaned or dropped.
- Out-of-range times are dropped.
- With no context, the prompt is unchanged.
- The defaults reach `keyword_search`.

Commit: `feat(agent): accept screen context to scope the co-pilot`.

### Task 11.2: Frontend agent types and label safety

**Files:**
- Modify: `frontend/src/hooks/useAgent.ts`, `frontend/src/hooks/useAgent.test.ts`

**Steps:**
1. `GlobeAction` gains `label?: string`. The type stays `"flyTo"`; drop `"highlight"`, which the backend never sends.
2. `cleanLabel(s)` strips Unicode control and bidi characters (`/[\u0000-\u001f\u007f-\u009f​-‏‪-‮⁦-⁩]/g`), collapses whitespace and caps at 80 characters. Apply it to every action label on receipt. This is the follow-up from the Phase 1 agent review.
3. `ask(question, context?)` sends `context` when given.
4. Tests:
   - control and bidi characters are stripped;
   - over-long labels are capped;
   - context is in the request body;
   - no context gives the same body as before.

### Task 11.3: Console UI

**Files:**
- Create: `frontend/src/components/CoPilot.tsx` (replaces `AgentPanel.tsx`), `frontend/src/components/CoPilot.test.tsx`
- Modify: `frontend/src/components/AgentMessage.tsx`, `frontend/src/app/soft-orbit.css` (port `.ctx`, `.quick`, `.msg*`, `.cite`, `.tools`, `.sources`, `.actions`, `.composer` from mockup 332–356)
- Delete: `frontend/src/components/AgentPanel.tsx`

**Layout,** inside the side panel's Co-pilot tab:
1. **Context pills** (`.ctx`): "Sees" followed by up to three pills for the current place (selected stories panel), topic (if not All) and window (`windowLabel`).
   - Each pill has a small `×` that removes it from the context for the next question only.
   - These are exactly what Task 11.1 sends.
2. **Messages:**
   - The user's message is a `.msg.user` bubble.
   - The assistant's is `.msg.bot` prose rendered by `react-markdown`, with numbered citation markers (`[1]`) as `.cite` pills. A pill click calls `onCitationClick` (fly to the place and open the source).
   - A `.sources` list follows.
3. **Tool line** (`.tools`): one quiet line from `activeTools` while streaming, e.g. "Searching articles…".
4. **Action pills** (`.actions`):
   - one "Fly to {label}" per normalised globe action, at most 3, using the cleaned label (it falls back to "Fly there");
   - plus "Show stories here", which opens the Stories tab for that point's cell.
   - "Open thread" and "Pin to board" arrive with PRs 16 and 18.
5. **Quick prompts** (`.quick`), from context:
   - with a place: "Brief me on {place}" and "What's driving coverage in {place}?";
   - with a topic only: "What's happening in {topic} today?";
   - with neither: "What's the biggest story right now?".
6. **Composer** (`.composer`): pill input "Ask about what you see" and an aurora send button (`aria-label="Ask"`). Stop and clear are icon buttons, and the disabled banner is kept.

**Tests:**
- Context pills render from props and removal excludes a field from the next `onAsk`.
- Citations render as pills and fire `onCitationClick`.
- Action pills render the cleaned labels.
- Quick prompts follow context.
- The send button is disabled when the input is empty.

Keep `data-testid`s `agent-panel` and `agent-input` so `e2e/agent.spec.ts` keeps working; extend it for context pills and action pills.

### Task 11.4: PR 11

1. Run all checks and the visual check.
2. Ask the live preview's co-pilot one question with a place selected, and confirm the context reached the backend: the container log line `Planned tools` shows the topic/window defaults.
3. Open the PR `feat(ui): co-pilot console with screen context (PR 11)`.

---

## After Phase 2

- Phase 3 (PRs 12–14) adds the hover card, links and alerts into the slots this phase reserves: the hover card at `--z-preview`, Links in the layer switcher, Surges in the bottom row's third track and "since your last visit" under the brand.
- Each of those PRs extends `layout.spec.ts` with its region.
