"use client";

import { useTheme } from "@/lib/theme";

export default function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  const toggle = () => setTheme(theme === "dark" ? "light" : "dark");

  return (
    <button
      onClick={toggle}
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
    </button>
  );
}
