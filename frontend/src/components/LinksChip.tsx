"use client";

interface LinksChipProps {
  /** The Links status ("No links in this window"), or null. */
  status: string | null;
  onOff: () => void;
}

/**
 * Links' own control where the layer switcher is hidden (phones, 760px and
 * below): a small "Links ✕" chip above the timeline while Links is on, which
 * turns it off. It also carries the Links status there. soft-orbit.css shows
 * it only at those widths; the rank stays at its default (Surprising).
 */
export default function LinksChip({ status, onOff }: LinksChipProps) {
  return (
    <button
      type="button"
      className="pillbar pill links-chip"
      data-testid="links-chip"
      aria-label="Turn Links off"
      onClick={onOff}
    >
      <span>Links</span>
      {status && <span className="links-chip-status">{status}</span>}
      <span aria-hidden="true">✕</span>
    </button>
  );
}
