"use client";

import { useTheme } from "@/lib/theme";
import type { ThemeChoice } from "@/lib/theme";

const CYCLE: ThemeChoice[] = ["system", "light", "dark"];

export default function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  const next = () => {
    const idx = CYCLE.indexOf(theme);
    setTheme(CYCLE[(idx + 1) % CYCLE.length]);
  };

  return (
    <button
      onClick={next}
      className="fixed top-3 right-3 z-50 flex h-8 w-8 items-center justify-center rounded-xl border transition-colors sm:top-5 sm:right-6 sm:h-9 sm:w-9"
      style={{
        background: "var(--surface-overlay)",
        backdropFilter: "blur(12px)",
        borderColor: "var(--border-subtle)",
      }}
      aria-label={`Theme: ${theme}. Click to switch.`}
      title={`Theme: ${theme}`}
    >
      {/* Sun icon (light mode) */}
      {theme === "light" && (
        <svg
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="none"
          stroke="var(--text-secondary)"
          strokeWidth="1.5"
          strokeLinecap="round"
        >
          <circle cx="8" cy="8" r="3" />
          <path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.17 3.17l1.06 1.06M11.77 11.77l1.06 1.06M3.17 12.83l1.06-1.06M11.77 4.23l1.06-1.06" />
        </svg>
      )}
      {/* Moon icon (dark mode) */}
      {theme === "dark" && (
        <svg
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="none"
          stroke="var(--text-secondary)"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M13.5 8.5a5.5 5.5 0 1 1-7-7 4.5 4.5 0 0 0 7 7z" />
        </svg>
      )}
      {/* System icon (monitor) */}
      {theme === "system" && (
        <svg
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="none"
          stroke="var(--text-secondary)"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <rect x="2" y="2" width="12" height="9" rx="1.5" />
          <path d="M5.5 14h5M8 11v3" />
        </svg>
      )}
      {/* System mode indicator dot */}
      {theme === "system" && (
        <span
          className="absolute -bottom-0.5 left-1/2 h-1 w-1 -translate-x-1/2 rounded-full bg-blue-500"
          style={{ boxShadow: "0 0 4px rgba(59,130,246,0.5)" }}
        />
      )}
    </button>
  );
}
