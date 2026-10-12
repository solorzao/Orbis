import type { ReactNode } from "react";

/**
 * The bottom row: layers | timeline | (surges, PR 14), one grid so the
 * tracks can never overlap. It must come after the side panel in the DOM:
 * soft-orbit.css moves it clear of the panel, and above the sheet, with
 * sibling selectors (`.side ~ .bottombar`).
 */
export default function BottomBar({ children }: { children: ReactNode }) {
  return <div className="bottombar">{children}</div>;
}
