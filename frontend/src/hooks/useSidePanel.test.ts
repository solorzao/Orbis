import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { createElement } from "react";
import { renderToString } from "react-dom/server";
import { hydrateRoot } from "react-dom/client";
import { renderHook, act } from "@testing-library/react";
import { useSidePanel, SIDE_WIDE_QUERY } from "./useSidePanel";

type Listener = () => void;

let wide = true;
let listeners: Listener[] = [];

function mockMatchMedia() {
  window.matchMedia = vi.fn((query: string) => ({
    get matches() {
      return query === SIDE_WIDE_QUERY && wide;
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

function resize(isWide: boolean) {
  act(() => {
    wide = isWide;
    listeners.forEach((l) => l());
  });
}

beforeEach(() => {
  wide = true;
  listeners = [];
  mockMatchMedia();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useSidePanel", () => {
  it("matches the sheet breakpoint: wide from 1180px", () => {
    expect(SIDE_WIDE_QUERY).toBe("(min-width: 1180px)");
  });

  it("starts on the Co-pilot tab", () => {
    const { result } = renderHook(() => useSidePanel());
    expect(result.current.tab).toBe("copilot");
  });

  it("opens by default on a wide screen", () => {
    const { result } = renderHook(() => useSidePanel());
    expect(result.current.open).toBe(true);
  });

  it("stays collapsed by default below 1180px", () => {
    wide = false;
    const { result } = renderHook(() => useSidePanel());
    expect(result.current.open).toBe(false);
  });

  it("is unknown on the server, then opens after hydration on a wide screen", () => {
    function Probe() {
      const { open } = useSidePanel();
      return createElement("p", null, open === null ? "unknown" : open ? "open" : "closed");
    }
    const html = renderToString(createElement(Probe));
    expect(html).toContain("unknown");

    const container = document.createElement("div");
    container.innerHTML = html;
    document.body.appendChild(container);
    const onRecoverableError = vi.fn();
    act(() => {
      hydrateRoot(container, createElement(Probe), { onRecoverableError });
    });
    expect(onRecoverableError).not.toHaveBeenCalled();
    expect(container.textContent).toBe("open");
    container.remove();
  });

  it("follows the width until the visitor chooses", () => {
    const { result } = renderHook(() => useSidePanel());
    resize(false);
    expect(result.current.open).toBe(false);
    resize(true);
    expect(result.current.open).toBe(true);

    act(() => result.current.setOpen(false));
    resize(false);
    resize(true);
    expect(result.current.open).toBe(false);
  });

  it("showStories switches to Stories and opens the panel", () => {
    wide = false;
    const { result } = renderHook(() => useSidePanel());
    act(() => result.current.showStories());
    expect(result.current.tab).toBe("stories");
    expect(result.current.open).toBe(true);
  });

  it("setTab switches tabs", () => {
    const { result } = renderHook(() => useSidePanel());
    act(() => result.current.setTab("stories"));
    expect(result.current.tab).toBe("stories");
    act(() => result.current.setTab("copilot"));
    expect(result.current.tab).toBe("copilot");
  });

  it("reads the media query once", () => {
    const { result, rerender } = renderHook(() => useSidePanel());
    rerender();
    act(() => result.current.setTab("stories"));
    resize(false);
    expect(window.matchMedia).toHaveBeenCalledTimes(1);
  });

  it("falls back to the window width without matchMedia", () => {
    // @ts-expect-error: simulate a browser without matchMedia
    delete window.matchMedia;
    const { result } = renderHook(() => useSidePanel());
    expect(result.current.open).toBe(window.innerWidth >= 1180);
  });
});
