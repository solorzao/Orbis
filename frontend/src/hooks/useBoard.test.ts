import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useBoard } from "./useBoard";
import { BOARD_KEY, MAX_PINS, type PinSnapshot } from "@/lib/board";

const snap = (title: string): PinSnapshot => ({
  title,
  place: null,
  lat: null,
  lng: null,
  time: null,
  url: null,
});

const stored = () => JSON.parse(localStorage.getItem(BOARD_KEY) ?? "null");

beforeEach(() => {
  localStorage.clear();
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("useBoard", () => {
  it("loads the stored board after mount", () => {
    localStorage.setItem(
      BOARD_KEY,
      JSON.stringify({
        pins: [{ item: "thread:7", snapshot: snap("Red Sea"), x: 0.2, y: 0.3, pinnedAt: 5 }],
      }),
    );
    const { result } = renderHook(() => useBoard());
    expect(result.current.ready).toBe(true);
    expect(result.current.pins.map((p) => p.item)).toEqual(["thread:7"]);
    expect(result.current.has("thread:7")).toBe(true);
    expect(result.current.has("thread:8")).toBe(false);
  });

  it("pins, moves and unpins, keeping each change in localStorage", () => {
    const { result } = renderHook(() => useBoard());
    act(() => {
      expect(result.current.toggle("place:48:2", snap("Paris"))).toBe("pinned");
    });
    expect(stored().pins.map((p: { item: string }) => p.item)).toEqual(["place:48:2"]);
    act(() => result.current.move("place:48:2", 0.25, 0.75));
    expect(stored().pins[0]).toMatchObject({ x: 0.25, y: 0.75 });
    act(() => {
      expect(result.current.toggle("place:48:2", snap("Paris"))).toBe("unpinned");
    });
    expect(result.current.pins).toEqual([]);
    expect(stored()).toEqual({ pins: [] });
  });

  it("holds 20 pins, then refuses more", () => {
    const { result } = renderHook(() => useBoard());
    act(() => {
      for (let i = 1; i <= MAX_PINS; i++) result.current.toggle(`thread:${i}`, snap(`T${i}`));
    });
    expect(result.current.pins).toHaveLength(MAX_PINS);
    expect(result.current.full).toBe(true);
    act(() => {
      expect(result.current.toggle("thread:99", snap("More"))).toBe("full");
    });
    expect(result.current.pins).toHaveLength(MAX_PINS);
    // A pin already in can still go.
    act(() => {
      expect(result.current.toggle("thread:1", snap("T1"))).toBe("unpinned");
    });
    expect(result.current.full).toBe(false);
  });

  it("works in memory when storage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    const { result } = renderHook(() => useBoard());
    act(() => {
      result.current.toggle("thread:7", snap("Red Sea"));
    });
    expect(result.current.pins.map((p) => p.item)).toEqual(["thread:7"]);
  });

  it("refreshes snapshots and merges shared pins", () => {
    const { result } = renderHook(() => useBoard());
    act(() => {
      result.current.toggle("thread:7", snap("Old title"));
    });
    act(() =>
      result.current.refresh([
        { item: "thread:7", snapshot: { title: "Red Sea", resolved_as: "thread:9" } },
      ]),
    );
    expect(result.current.pins.map((p) => [p.item, p.snapshot.title])).toEqual([
      ["thread:9", "Red Sea"],
    ]);
    let outcome = { added: 0, skipped: 0 };
    act(() => {
      outcome = result.current.merge([
        { item: "thread:9", snapshot: snap("Dup") },
        { item: "place:48:2", snapshot: snap("Paris") },
      ]);
    });
    expect(outcome).toEqual({ added: 1, skipped: 0 });
    expect(result.current.pins).toHaveLength(2);
  });

  it("follows another tab's changes to the board", () => {
    const { result } = renderHook(() => useBoard());
    const value = JSON.stringify({
      pins: [{ item: "thread:3", snapshot: snap("Elsewhere"), x: 0, y: 0, pinnedAt: 1 }],
    });
    act(() => {
      localStorage.setItem(BOARD_KEY, value);
      window.dispatchEvent(new StorageEvent("storage", { key: BOARD_KEY, newValue: value }));
    });
    expect(result.current.pins.map((p) => p.item)).toEqual(["thread:3"]);
  });
});
