"use client";

import { motion } from "framer-motion";
import { PanelEntry } from "@/types/news";

interface PanelTabProps {
  entry: PanelEntry;
  onExpand: (panelId: string) => void;
  onClose: (panelId: string) => void;
}

export default function PanelTab({ entry, onExpand, onClose }: PanelTabProps) {
  const isLoading = entry.articlesLoading || entry.summaryLoading;
  const locationName =
    entry.point.locationName ||
    `${entry.point.lat.toFixed(1)}\u00B0, ${entry.point.lng.toFixed(1)}\u00B0`;
  // Truncate to first part before comma for compact display
  const shortName = locationName.split(",")[0].trim();

  return (
    <motion.div
      layout
      initial={{ x: 40, opacity: 0, scale: 0.95 }}
      animate={{ x: 0, opacity: 1, scale: 1 }}
      exit={{ x: 40, opacity: 0, scale: 0.95 }}
      transition={{ type: "spring", stiffness: 400, damping: 30 }}
      className="group flex cursor-pointer items-center gap-2 rounded-xl border px-3 py-2"
      style={{
        background: "var(--surface-overlay)",
        backdropFilter: "blur(12px)",
        borderColor: "var(--border-subtle)",
        minWidth: "160px",
        maxWidth: "200px",
      }}
      onClick={() => onExpand(entry.panelId)}
    >
      {/* Topic color dot or loading spinner */}
      {isLoading ? (
        <span
          className="h-2 w-2 shrink-0 animate-spin rounded-full border border-transparent border-t-blue-400"
          style={{
            borderRightColor: "transparent",
            borderBottomColor: "transparent",
            borderLeftColor: "transparent",
          }}
        />
      ) : (
        <span
          className="h-2 w-2 shrink-0 rounded-full"
          style={{
            backgroundColor: entry.point.color,
            boxShadow: `0 0 4px ${entry.point.color}60`,
          }}
        />
      )}

      {/* Location name + count */}
      <div className="flex-1 overflow-hidden">
        <p className="truncate text-[11px] font-medium" style={{ color: "var(--text-primary)" }}>
          {shortName}
        </p>
        <p className="text-[9px]" style={{ color: "var(--text-muted)" }}>
          {isLoading ? "Loading..." : `${entry.point.count} stories`}
        </p>
      </div>

      {/* Close button */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          onClose(entry.panelId);
        }}
        className="shrink-0 rounded p-0.5 opacity-0 transition-opacity group-hover:opacity-100"
        style={{ color: "var(--text-muted)" }}
        aria-label="Remove from queue"
      >
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
          <path
            d="M2 2L8 8M8 2L2 8"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </svg>
      </button>
    </motion.div>
  );
}
