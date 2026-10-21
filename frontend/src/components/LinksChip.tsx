"use client";

interface LinksChipProps {
  /** The overlay on: Links, or Relations (they are never on together). */
  label?: "Links" | "Relations";
  /** Its status ("No links in this window"), or null. */
  status: string | null;
  onOff: () => void;
}

/**
 * The arc overlays' own control where the layer switcher is hidden (phones,
 * 760px and below): a small "Links ✕" (or "Relations ✕") chip above the
 * timeline while that overlay is on, which turns it off. It also carries its
 * status there. soft-orbit.css shows it only at those widths; the rank and
 * the class switch stay at their defaults.
 */
export default function LinksChip({ label = "Links", status, onOff }: LinksChipProps) {
  return (
    <button
      type="button"
      className="pillbar pill links-chip"
      data-testid="links-chip"
      aria-label={`Turn ${label} off`}
      onClick={onOff}
    >
      <span>{label}</span>
      {status && <span className="links-chip-status">{status}</span>}
      <span aria-hidden="true">✕</span>
    </button>
  );
}
