import type { ReactNode } from "react";

/**
 * The bottom row: layers | timeline | breaking ticker, one grid so the
 * tracks can never overlap. It must come after the side panel in the DOM:
 * below 1180px soft-orbit.css lifts it above the sheet with sibling
 * selectors (`.side ~ *`).
 */
export default function BottomBar({ children }: { children: ReactNode }) {
  return <div className="bottombar">{children}</div>;
}
