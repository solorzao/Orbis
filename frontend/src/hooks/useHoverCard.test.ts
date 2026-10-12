import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, renderHook } from "@testing-library/react";
import { HIDE_GRACE_MS, SHOW_DELAY_MS, useHoverCard } from "./useHoverCard";
import type { GlobePoint } from "@/types/news";

function point(lat: number, lng: number, count = 5): GlobePoint {
  return {
    id: `api-${lat}`,
    lat,
    lng,
    size: 1,
    color: "#ab9dff",
    articles: [],
    isCluster: true,
    count,
    topic: "Politics",
  };
}
const PARIS = point(48.5, 2.5);
const LONDON = point(51.5, -0.5);

const advance = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });

const NOW = Date.parse("2026-10-12T14:30:00Z");

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useHoverCard with a mouse", () => {
  const mouse = () => renderHook(() => useHoverCard(false));

  it("shows the card after 150 ms over the same dot", async () => {
    const { result } = mouse();
    act(() => result.current.onPointHover(PARIS));
    expect(result.current.card).toBeNull();
    expect(result.current.focus).toBe(PARIS); // the preview's dwell starts on the dot

    await advance(SHOW_DELAY_MS - 1);
    expect(result.current.card).toBeNull();
    await advance(1);
    expect(result.current.card).toEqual({ point: PARIS, shownAt: NOW + SHOW_DELAY_MS });
  });

  it("never shows for a dot the pointer only crosses", async () => {
    const { result } = mouse();
    act(() => result.current.onPointHover(PARIS));
    await advance(SHOW_DELAY_MS - 50);
    act(() => result.current.onPointHover(null));
    await advance(SHOW_DELAY_MS + HIDE_GRACE_MS);
    expect(result.current.card).toBeNull();
    expect(result.current.focus).toBeNull();
  });

  it("stays while the pointer is on the card, and goes once it leaves", async () => {
    const { result } = mouse();
    act(() => result.current.onPointHover(PARIS));
    await advance(SHOW_DELAY_MS);

    // Off the dot, towards the card: a short grace, then the card holds it.
    act(() => result.current.onPointHover(null));
    await advance(HIDE_GRACE_MS - 50);
    act(() => result.current.onCardEnter());
    await advance(HIDE_GRACE_MS * 3);
    expect(result.current.card?.point).toBe(PARIS);
    expect(result.current.focus).toBe(PARIS); // the preview keeps loading meanwhile

    act(() => result.current.onCardLeave());
    await advance(HIDE_GRACE_MS - 1);
    expect(result.current.card).not.toBeNull();
    await advance(1);
    expect(result.current.card).toBeNull();
    expect(result.current.focus).toBeNull();
  });

  it("hides after the grace when the pointer leaves the dot for the globe", async () => {
    const { result } = mouse();
    act(() => result.current.onPointHover(PARIS));
    await advance(SHOW_DELAY_MS);
    act(() => result.current.onPointHover(null));
    await advance(HIDE_GRACE_MS);
    expect(result.current.card).toBeNull();
  });

  it("moves to another dot after its own 150 ms, keeping the last card meanwhile", async () => {
    const { result } = mouse();
    act(() => result.current.onPointHover(PARIS));
    await advance(SHOW_DELAY_MS);
    act(() => result.current.onPointHover(LONDON));
    expect(result.current.focus).toBe(LONDON);
    await advance(SHOW_DELAY_MS - 1);
    expect(result.current.card?.point).toBe(PARIS);
    await advance(1);
    expect(result.current.card?.point).toBe(LONDON);
  });

  it("takes a refreshed point for the same place at once", async () => {
    const { result } = mouse();
    act(() => result.current.onPointHover(PARIS));
    await advance(SHOW_DELAY_MS);
    const refreshed = point(48.5, 2.5, 9);
    act(() => result.current.onPointHover(refreshed));
    expect(result.current.card?.point).toBe(refreshed);
  });

  it("hides on Escape, and stays hidden until the pointer leaves the dot", async () => {
    const { result } = mouse();
    act(() => result.current.onPointHover(PARIS));
    await advance(SHOW_DELAY_MS);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(result.current.card).toBeNull();
    expect(result.current.focus).toBeNull();
    // globe.gl reports the same dot again (points refreshed): still hidden.
    act(() => result.current.onPointHover(point(48.5, 2.5, 9)));
    await advance(SHOW_DELAY_MS * 2);
    expect(result.current.card).toBeNull();

    act(() => result.current.onPointHover(null));
    act(() => result.current.onPointHover(PARIS));
    await advance(SHOW_DELAY_MS);
    expect(result.current.card?.point).toBe(PARIS);
  });

  it("ignores other keys", async () => {
    const { result } = mouse();
    act(() => result.current.onPointHover(PARIS));
    await advance(SHOW_DELAY_MS);
    fireEvent.keyDown(window, { key: "Enter" });
    expect(result.current.card).not.toBeNull();
  });

  it("hides when the dot is clicked (its panel opens)", async () => {
    const { result } = mouse();
    act(() => result.current.onPointHover(PARIS));
    await advance(SHOW_DELAY_MS);
    act(() => result.current.dismiss());
    expect(result.current.card).toBeNull();
    await advance(SHOW_DELAY_MS * 2);
    expect(result.current.card).toBeNull();
  });
});

describe("useHoverCard on a touch screen", () => {
  const touch = () => renderHook(() => useHoverCard(true));

  it("ignores hovers: a tap shows the card at once", () => {
    const { result } = touch();
    act(() => result.current.onPointHover(PARIS));
    expect(result.current.card).toBeNull();
    expect(result.current.focus).toBeNull();

    let opens = true;
    act(() => {
      opens = result.current.tap(PARIS);
    });
    expect(opens).toBe(false);
    expect(result.current.card).toEqual({ point: PARIS, shownAt: NOW });
    expect(result.current.focus).toBe(PARIS);
  });

  it("opens the panel on a second tap of the same dot", () => {
    const { result } = touch();
    act(() => void result.current.tap(PARIS));
    let opens = false;
    act(() => {
      opens = result.current.tap(point(48.5, 2.5, 9));
    });
    expect(opens).toBe(true);
    expect(result.current.card).toBeNull();
  });

  it("moves to another dot on its first tap", () => {
    const { result } = touch();
    act(() => void result.current.tap(PARIS));
    let opens = true;
    act(() => {
      opens = result.current.tap(LONDON);
    });
    expect(opens).toBe(false);
    expect(result.current.card?.point).toBe(LONDON);
  });

  it("hides on a tap off the dots", () => {
    const { result } = touch();
    act(() => void result.current.tap(PARIS));
    act(() => result.current.onEmptyTap());
    expect(result.current.card).toBeNull();
  });

  it("hides on a tap anywhere else on the page, but not on the card or the globe", () => {
    const card = document.createElement("article");
    card.append(document.createElement("button"));
    const globe = document.createElement("div");
    globe.dataset.testid = "globe";
    globe.append(document.createElement("canvas"));
    const tab = document.createElement("button");
    document.body.append(card, globe, tab);
    const { result } = renderHook(() => useHoverCard(true, { current: card }));
    act(() => void result.current.tap(PARIS));

    fireEvent.pointerDown(card.querySelector("button")!);
    expect(result.current.card).not.toBeNull();
    // The globe's own taps go through tap and onEmptyTap.
    fireEvent.pointerDown(globe.querySelector("canvas")!);
    expect(result.current.card).not.toBeNull();

    fireEvent.pointerDown(tab);
    expect(result.current.card).toBeNull();
    card.remove();
    globe.remove();
    tab.remove();
  });

  it("leaves a mouse's clicks elsewhere alone (the pointer leaving hides it)", async () => {
    const tab = document.createElement("button");
    document.body.append(tab);
    const { result } = renderHook(() => useHoverCard(false, { current: null }));
    act(() => result.current.onPointHover(PARIS));
    await advance(SHOW_DELAY_MS);
    fireEvent.pointerDown(tab);
    expect(result.current.card).not.toBeNull();
    tab.remove();
  });
});

describe("useHoverCard when the dots change", () => {
  it("hides the card when its place is no longer a dot (a new window or topic)", async () => {
    const { result, rerender } = renderHook(
      ({ points }: { points: GlobePoint[] }) => useHoverCard(false, undefined, points),
      { initialProps: { points: [PARIS, LONDON] } },
    );
    act(() => result.current.onPointHover(PARIS));
    await advance(SHOW_DELAY_MS);
    act(() => result.current.onCardEnter()); // the pointer rests on the card

    // Refreshed dots that still have Paris: the card stays.
    rerender({ points: [point(48.5, 2.5, 9), LONDON] });
    expect(result.current.card?.point.lat).toBe(48.5);

    // Paris has no stories in the new window: the card goes, and stays gone.
    rerender({ points: [LONDON] });
    await advance(0);
    expect(result.current.card).toBeNull();
    rerender({ points: [PARIS, LONDON] });
    expect(result.current.card).toBeNull();
  });
});
