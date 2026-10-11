"use client";

import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import type { SideTab } from "@/hooks/useSidePanel";

const TABS: { id: SideTab; label: string }[] = [
  { id: "copilot", label: "Co-pilot" },
  { id: "stories", label: "Stories" },
];

interface SidePanelProps {
  tab: SideTab;
  onTabChange: (tab: SideTab) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  copilot: ReactNode;
  stories: ReactNode;
  /** Places open in the Stories tab, shown as a badge on the collapsed pill. */
  storiesCount?: number;
}

/** False when CSS hides the element (the reopen pill is hidden on the sheet). */
function isShown(el: HTMLElement): boolean {
  return typeof el.checkVisibility === "function" ? el.checkVisibility() : !el.hidden;
}

/**
 * Co-pilot and Stories in one glass panel (mockup `.side`). From 1180px it
 * floats on the right and collapses to a pill at the same corner; below that
 * it is a bottom sheet that collapses to its tab bar (soft-orbit.css).
 *
 * The tabs follow the WAI-ARIA tabs pattern: a roving tabindex, arrow keys,
 * Home and End, with automatic activation. Focus moves only when the control
 * that had it disappears: to the pill on collapse, and back to the active
 * tab when the pill reopens the panel.
 */
export default function SidePanel({
  tab,
  onTabChange,
  open,
  onOpenChange,
  copilot,
  stories,
  storiesCount = 0,
}: SidePanelProps) {
  const id = useId();
  const tabId = (t: SideTab) => `${id}-tab-${t}`;
  const panelId = (t: SideTab) => `${id}-panel-${t}`;
  const content: Record<SideTab, ReactNode> = { copilot, stories };

  const tabRefs = useRef<Partial<Record<SideTab, HTMLButtonElement | null>>>({});
  const pillRef = useRef<HTMLButtonElement>(null);
  const focusAfter = useRef<"tab" | "pill" | null>(null);

  useEffect(() => {
    const target = focusAfter.current;
    focusAfter.current = null;
    if (target === "tab") tabRefs.current[tab]?.focus();
    if (target === "pill" && pillRef.current && isShown(pillRef.current)) pillRef.current.focus();
  }, [open, tab]);

  const select = (next: SideTab) => {
    onTabChange(next);
    if (!open) onOpenChange(true); // the sheet's tab bar opens the sheet
  };

  const onTabKeyDown = (e: KeyboardEvent<HTMLButtonElement>, current: SideTab) => {
    const i = TABS.findIndex((t) => t.id === current);
    const last = TABS.length - 1;
    const j =
      e.key === "ArrowRight"
        ? (i + 1) % TABS.length
        : e.key === "ArrowLeft"
          ? (i + last) % TABS.length
          : e.key === "Home"
            ? 0
            : e.key === "End"
              ? last
              : null;
    if (j === null) return;
    e.preventDefault();
    const next = TABS[j].id;
    select(next);
    tabRefs.current[next]?.focus();
  };

  const places = `${storiesCount} ${storiesCount === 1 ? "place" : "places"} in Stories`;

  return (
    <>
      <section
        className="glass side"
        aria-label="Co-pilot and stories"
        data-testid="side-panel"
        data-open={open}
      >
        <div className="ghead">
          <div className="seg" role="tablist" aria-label="Side panel">
            {TABS.map((t) => (
              <button
                key={t.id}
                ref={(el) => {
                  tabRefs.current[t.id] = el;
                }}
                type="button"
                role="tab"
                id={tabId(t.id)}
                data-testid={`side-tab-${t.id}`}
                aria-selected={tab === t.id}
                aria-controls={panelId(t.id)}
                tabIndex={tab === t.id ? 0 : -1}
                onClick={() => select(t.id)}
                onKeyDown={(e) => onTabKeyDown(e, t.id)}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="end">
            <button
              type="button"
              className="iconbtn side-collapse"
              data-testid="side-collapse"
              aria-label={open ? "Collapse panel" : "Expand panel"}
              aria-expanded={open}
              aria-controls={TABS.map((t) => panelId(t.id)).join(" ")}
              onClick={() => {
                if (open) focusAfter.current = "pill";
                onOpenChange(!open);
              }}
            >
              <svg
                width="12"
                height="12"
                viewBox="0 0 12 12"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M2.5 4.5 6 8l3.5-3.5" />
              </svg>
            </button>
          </div>
        </div>

        {TABS.map((t) => (
          <div
            key={t.id}
            id={panelId(t.id)}
            role="tabpanel"
            aria-labelledby={tabId(t.id)}
            className={`gbody side-body side-body-${t.id}`}
            hidden={tab !== t.id}
          >
            {content[t.id]}
          </div>
        ))}
      </section>

      <button
        ref={pillRef}
        type="button"
        className="pillbar pill lg side-open"
        data-testid="side-open"
        hidden={open}
        aria-label={storiesCount > 0 ? `Open Co-pilot, ${places}` : "Open Co-pilot"}
        onClick={() => {
          focusAfter.current = "tab";
          onOpenChange(true);
        }}
      >
        Co-pilot
        {storiesCount > 0 && <span className="num">{storiesCount}</span>}
      </button>
    </>
  );
}
