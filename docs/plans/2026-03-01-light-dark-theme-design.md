# Light/Dark Theme System Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a full light/dark theme system with CSS custom properties, system preference detection, manual toggle, and globe texture swapping.

**Architecture:** CSS custom properties as single source of truth for all theme colors. A React context manages theme state (system/light/dark) persisted in localStorage. Components replace hard-coded colors with `var(--token)` references.

**Tech Stack:** CSS custom properties, React Context, localStorage, `prefers-color-scheme` media query

---

## Theme Architecture

- `data-theme="light"` or `data-theme="dark"` attribute on `<html>` controls active theme
- CSS variables defined in `globals.css` under `[data-theme="dark"]` and `[data-theme="light"]` selectors
- Topic colors, sentiment colors, and blue accent (#3B82F6) stay the same in both modes
- Globe texture and atmosphere color swapped via JS (not CSS vars)

## Theme State Management

**ThemeProvider context** (`lib/theme.tsx`):
- Three states: `"system"` | `"light"` | `"dark"`
- Exposes `{ theme, resolvedTheme, setTheme }`
- `theme` = user's choice, `resolvedTheme` = actual active mode
- Persisted in `localStorage` under `orbis-theme`
- On load: check localStorage → if "system" or absent, read `prefers-color-scheme` → set `data-theme` on `<html>`
- Listens for OS preference changes when in "system" mode

**Toggle button** (`components/ThemeToggle.tsx`):
- Top-right corner, sun/moon icon
- Cycles: system → light → dark → system
- Subtle dot indicator for "system" mode vs manual override

**Layout** (`app/layout.tsx`):
- Wraps app in ThemeProvider

## Color Palette

### Dark Mode (default)

```
--bg-page:          #030712
--surface-panel:    rgba(8, 12, 24, 0.82)
--surface-card:     rgba(15, 20, 35, 0.6)
--surface-overlay:  rgba(8, 12, 24, 0.65)
--text-primary:     #e2e8f0
--text-secondary:   #94a3b8
--text-muted:       #64748b
--border-subtle:    rgba(255, 255, 255, 0.06)
--border-accent:    rgba(59, 130, 246, 0.12)
--vignette:         rgba(3, 7, 18, 0.6)
--shadow:           rgba(0, 0, 0, 0.4)
--inset-highlight:  rgba(255, 255, 255, 0.03)
```

Globe: night texture + `#1a3a5c` atmosphere

### Light Mode

```
--bg-page:          #f0f4f8
--surface-panel:    rgba(255, 255, 255, 0.85)
--surface-card:     rgba(255, 255, 255, 0.7)
--surface-overlay:  rgba(255, 255, 255, 0.75)
--text-primary:     #1e293b
--text-secondary:   #475569
--text-muted:       #94a3b8
--border-subtle:    rgba(0, 0, 0, 0.08)
--border-accent:    rgba(59, 130, 246, 0.2)
--vignette:         rgba(240, 244, 248, 0.5)
--shadow:           rgba(0, 0, 0, 0.1)
--inset-highlight:  rgba(255, 255, 255, 0.5)
```

Globe: blue marble texture + `#87CEEB` atmosphere

## Component Migration

### NewsPanel.tsx (~11 color instances)
- Panel background → `var(--surface-panel)`
- Card backgrounds → `var(--surface-card)`
- Border left → `var(--border-accent)`
- `text-slate-*` classes → `text-[var(--text-*)]` or CSS var equivalents
- AI briefing blue tint stays same in both modes
- Skeleton shimmer adapts background

### TopicFilter.tsx (~6 instances)
- Bar background → `var(--surface-overlay)`
- Edge fades → uses `var(--bg-page)` with opacity
- Box shadow → `var(--shadow)`
- Inactive text → `var(--text-muted)`

### Globe.tsx (~3 instances + JS)
- Vignette gradient → `var(--vignette)`
- Tooltip HTML string → reads CSS vars via getComputedStyle
- Texture + atmosphere → swapped via `useTheme()` hook

### page.tsx (~4 instances)
- Status bar background/text
- Logo text shadow adjusts per mode
- `bg-[#030712]` → `bg-[var(--bg-page)]`

### globals.css
- Define both theme variable sets
- Scrollbar colors adapt

## What Stays the Same

- Topic colors (Politics purple, Conflict red, etc.)
- Sentiment colors (green/amber/orange/red)
- Blue accent (#3B82F6)
- Backdrop blur on all glass panels
- All animations and transitions
