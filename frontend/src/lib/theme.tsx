"use client";

import { createContext, useContext, useEffect, useState, useCallback } from "react";

export type ThemeChoice = "light" | "dark";

interface ThemeContextValue {
  theme: ThemeChoice;
  setTheme: (theme: ThemeChoice) => void;
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

const STORAGE_KEY = "orbis-theme";

function getSystemTheme(): ThemeChoice {
  if (typeof window === "undefined") return "dark";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme: ThemeChoice) {
  document.documentElement.setAttribute("data-theme", theme);
}

function getInitialChoice(): ThemeChoice {
  if (typeof window === "undefined") return "dark";
  const stored = localStorage.getItem(STORAGE_KEY) as ThemeChoice | null;
  if (stored && (stored === "light" || stored === "dark")) return stored;
  return getSystemTheme();
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<ThemeChoice>("dark");

  // Hydrate real theme on mount (avoids SSR mismatch)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    const real = getInitialChoice();
    setThemeState(real);
    applyTheme(real);
  }, []);

  const setTheme = useCallback((newTheme: ThemeChoice) => {
    setThemeState(newTheme);
    localStorage.setItem(STORAGE_KEY, newTheme);
    applyTheme(newTheme);
  }, []);

  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used within a ThemeProvider");
  return context;
}
