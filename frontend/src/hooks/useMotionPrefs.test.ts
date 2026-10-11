import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useMotionPrefs, LOW_POWER_KEY } from "./useMotionPrefs";

type Listener = () => void;

let reducedMatches = false;
let listeners: Listener[] = [];
let cores: number | undefined = 8;

function mockMatchMedia() {
  window.matchMedia = vi.fn((query: string) => ({
    get matches() {
      return query === "(prefers-reduced-motion: reduce)" && reducedMatches;
    },
    media: query,
    onchange: null,
    addEventListener: (_: string, l: Listener) => listeners.push(l),
    removeEventListener: (_: string, l: Listener) => {
      listeners = listeners.filter((x) => x !== l);
    },
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia;
}

beforeEach(() => {
  reducedMatches = false;
  listeners = [];
  cores = 8;
  mockMatchMedia();
  Object.defineProperty(window.navigator, "hardwareConcurrency", {
    configurable: true,
    get: () => cores,
  });
  window.localStorage.clear();
  document.documentElement.classList.remove("low-power");
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useMotionPrefs", () => {
  it.each([
    { reduce: false, hw: 8, reduced: false, lowPower: false },
    { reduce: true, hw: 8, reduced: true, lowPower: false },
    { reduce: false, hw: 4, reduced: false, lowPower: true },
    { reduce: true, hw: 2, reduced: true, lowPower: true },
  ])(
    "reduce=$reduce, $hw cores gives reduced=$reduced, lowPower=$lowPower",
    ({ reduce, hw, reduced, lowPower }) => {
      reducedMatches = reduce;
      cores = hw;
      const { result } = renderHook(() => useMotionPrefs());
      expect(result.current).toEqual({ reduced, lowPower });
    },
  );

  it("follows prefers-reduced-motion when it changes", () => {
    const { result } = renderHook(() => useMotionPrefs());
    expect(result.current.reduced).toBe(false);

    act(() => {
      reducedMatches = true;
      listeners.forEach((l) => l());
    });
    expect(result.current.reduced).toBe(true);
  });

  it("treats an unknown core count as a capable device", () => {
    cores = undefined;
    const { result } = renderHook(() => useMotionPrefs());
    expect(result.current.lowPower).toBe(false);
  });

  it('forces low power on with localStorage "1", even on a fast device', () => {
    cores = 16;
    window.localStorage.setItem(LOW_POWER_KEY, "1");
    const { result } = renderHook(() => useMotionPrefs());
    expect(result.current.lowPower).toBe(true);
  });

  it("any other stored value overrides the core count and turns low power off", () => {
    cores = 2;
    window.localStorage.setItem(LOW_POWER_KEY, "0");
    const { result } = renderHook(() => useMotionPrefs());
    expect(result.current.lowPower).toBe(false);
  });

  it("falls back to the core count when storage throws", () => {
    cores = 2;
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    const { result } = renderHook(() => useMotionPrefs());
    expect(result.current.lowPower).toBe(true);
  });

  it("sets low-power on <html> while mounted and removes it on unmount", () => {
    cores = 2;
    const { unmount } = renderHook(() => useMotionPrefs());
    expect(document.documentElement.classList.contains("low-power")).toBe(true);
    unmount();
    expect(document.documentElement.classList.contains("low-power")).toBe(false);
  });

  it("leaves <html> without low-power on a capable device", () => {
    renderHook(() => useMotionPrefs());
    expect(document.documentElement.classList.contains("low-power")).toBe(false);
  });

  it("works without matchMedia (reduced is false)", () => {
    // @ts-expect-error simulating an environment without matchMedia
    delete window.matchMedia;
    const { result } = renderHook(() => useMotionPrefs());
    expect(result.current.reduced).toBe(false);
  });
});
