import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import {
  useBoardLinks,
  useBoardMemo,
  useBoardMirror,
  useBoardRefresh,
  useSharedBoard,
} from "./useBoardData";
import { useBoard } from "./useBoard";
import { analyzePins, fetchBoardLinks, resolveItems } from "@/lib/boardApi";
import { BOARD_KEY, encodeShare, type Pin, type PinSnapshot } from "@/lib/board";

vi.mock("@/lib/boardApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/boardApi")>()),
  fetchBoardLinks: vi.fn(),
  analyzePins: vi.fn(),
  resolveItems: vi.fn(),
}));

const snap = (title: string): PinSnapshot => ({
  title,
  place: null,
  lat: null,
  lng: null,
  time: null,
  url: null,
});
const pin = (item: string): Pin => ({ item, snapshot: snap(item), x: 0, y: 0, pinnedAt: 0 });
const EDGE = { a: "thread:1", b: "thread:2", kind: "same_thread" as const, label: "same thread" };

beforeEach(() => {
  vi.mocked(fetchBoardLinks).mockReset();
  vi.mocked(analyzePins).mockReset();
  vi.mocked(resolveItems).mockReset();
  localStorage.clear();
});
afterEach(() => {
  vi.useRealTimers();
  window.history.replaceState(null, "", "/");
});

describe("useBoardLinks", () => {
  it("asks for the edges once two or more pins show, after a short pause", async () => {
    vi.useFakeTimers();
    vi.mocked(fetchBoardLinks).mockResolvedValue({ edges: [EDGE], coCoverageChecked: false });
    const { result, rerender } = renderHook(({ items, on }) => useBoardLinks(items, on), {
      initialProps: { items: ["thread:1"], on: true },
    });
    expect(result.current).toEqual({ edges: [], coCoverageChecked: true, loading: false });
    rerender({ items: ["thread:1", "thread:2"], on: true });
    expect(result.current.loading).toBe(true);
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    expect(fetchBoardLinks).toHaveBeenCalledWith(["thread:1", "thread:2"], expect.any(AbortSignal));
    expect(result.current).toEqual({ edges: [EDGE], coCoverageChecked: false, loading: false });
  });

  it("asks nothing while the board is closed", () => {
    renderHook(() => useBoardLinks(["thread:1", "thread:2"], false));
    expect(fetchBoardLinks).not.toHaveBeenCalled();
  });

  it("ignores an answer for pins that have changed since", async () => {
    vi.useFakeTimers();
    let answer: (v: { edges: (typeof EDGE)[]; coCoverageChecked: boolean }) => void = () => {};
    vi.mocked(fetchBoardLinks).mockImplementationOnce(
      () => new Promise((resolve) => (answer = resolve)),
    );
    vi.mocked(fetchBoardLinks).mockResolvedValue({ edges: [], coCoverageChecked: true });
    const { result, rerender } = renderHook(({ items }) => useBoardLinks(items, true), {
      initialProps: { items: ["thread:1", "thread:2"] },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    rerender({ items: ["thread:1", "thread:3"] });
    await act(async () => {
      answer({ edges: [EDGE], coCoverageChecked: true });
      await vi.runAllTimersAsync();
    });
    expect(result.current.edges).toEqual([]);
  });
});

describe("useBoardMemo", () => {
  const PINS = [pin("thread:1"), pin("thread:2")];
  const MEMO = { sections: [], citations: [], message: "Paused.", items: ["thread:1", "thread:2"] };

  it("analyzes the pins, busy until the memo lands", async () => {
    let answer: (m: typeof MEMO) => void = () => {};
    vi.mocked(analyzePins).mockImplementation(() => new Promise((resolve) => (answer = resolve)));
    const { result } = renderHook(() => useBoardMemo(PINS));
    act(() => result.current.analyze());
    expect(result.current.analyzing).toBe(true);
    expect(analyzePins).toHaveBeenCalledWith(PINS, expect.any(AbortSignal));
    await act(async () => answer(MEMO));
    expect(result.current).toMatchObject({ memo: MEMO, analyzing: false });
    act(() => result.current.dismiss());
    expect(result.current.memo).toBeNull();
  });

  it("drops the memo once the pins change: its numbers would cite others", async () => {
    vi.mocked(analyzePins).mockResolvedValue(MEMO);
    const { result, rerender } = renderHook(({ pins }) => useBoardMemo(pins), {
      initialProps: { pins: PINS },
    });
    await act(async () => result.current.analyze());
    expect(result.current.memo).toEqual(MEMO);
    // Moved cards keep it...
    rerender({ pins: PINS.map((p) => ({ ...p, x: 0.5 })) });
    expect(result.current.memo).toEqual(MEMO);
    // ...a pin removed doesn't.
    rerender({ pins: PINS.slice(0, 1) });
    expect(result.current.memo).toBeNull();
  });
});

describe("useBoardMirror", () => {
  const at = (item: string, lat: number, lng: number, x = 0): Pin => ({
    ...pin(item),
    snapshot: { ...snap(item), lat, lng },
    x,
  });
  const EDGES = [{ ...EDGE }];

  it("mirrors the board only while it shows", () => {
    const pins = [at("thread:1", 10, 10), at("thread:2", 40, 40)];
    const { result, rerender } = renderHook(({ shown }) => useBoardMirror(pins, EDGES, shown), {
      initialProps: { shown: false },
    });
    expect(result.current).toBeNull();
    rerender({ shown: true });
    expect(result.current?.places).toHaveLength(2);
    expect(result.current?.arcs).toHaveLength(1);
  });

  it("keeps the same object while only cards move, so the globe keeps its arcs", () => {
    const { result, rerender } = renderHook(({ pins }) => useBoardMirror(pins, EDGES, true), {
      initialProps: { pins: [at("thread:1", 10, 10), at("thread:2", 40, 40)] },
    });
    const first = result.current;
    rerender({ pins: [at("thread:1", 10, 10, 0.7), at("thread:2", 40, 40)] });
    expect(result.current).toBe(first);
    rerender({ pins: [at("thread:1", 10, 10), at("thread:2", 41, 40)] });
    expect(result.current).not.toBe(first);
  });
});

describe("useBoardRefresh", () => {
  it("refreshes the pins' snapshots each time the board opens", async () => {
    localStorage.setItem(
      BOARD_KEY,
      JSON.stringify({
        pins: [{ item: "thread:7", snapshot: snap("Old"), x: 0, y: 0, pinnedAt: 1 }],
      }),
    );
    vi.mocked(resolveItems).mockResolvedValue({
      items: [{ item: "thread:7", snapshot: { title: "New" } }],
      rejected: [],
    });
    const { result, rerender } = renderHook(
      ({ open }) => {
        const board = useBoard();
        useBoardRefresh(open, board);
        return board;
      },
      { initialProps: { open: false } },
    );
    expect(resolveItems).not.toHaveBeenCalled();
    rerender({ open: true });
    await waitFor(() => expect(result.current.pins[0].snapshot.title).toBe("New"));
    expect(resolveItems).toHaveBeenCalledWith(["thread:7"], expect.any(AbortSignal));
  });
});

describe("useSharedBoard", () => {
  function render(onOpen = vi.fn(), announce = vi.fn()) {
    const hook = renderHook(() => {
      const board = useBoard();
      const shared = useSharedBoard(board, { onOpen, announce });
      return { board, shared };
    });
    return { ...hook, onOpen, announce };
  }
  const link = (ids: string[]) =>
    window.history.replaceState(null, "", `/?board=${encodeShare(ids)}&x=1`);

  it("opens a shared board on an empty one, its pins resolved, and drops the link", async () => {
    link(["thread:7", "place:48:2"]);
    vi.mocked(resolveItems).mockResolvedValue({
      items: [
        { item: "thread:7", snapshot: { title: "Red Sea" } },
        { item: "place:48:2", snapshot: null },
      ],
      rejected: [],
    });
    const { result, onOpen } = render();
    await waitFor(() => expect(result.current.board.pins).toHaveLength(2));
    expect(result.current.board.pins.map((p) => p.snapshot.title)).toEqual([
      "Red Sea",
      "48.5°, 2.5°",
    ]);
    expect(onOpen).toHaveBeenCalled();
    expect(result.current.shared.offer).toBeNull();
    expect(window.location.search).toBe("?x=1");
  });

  it("asks before merging into a board with pins", async () => {
    localStorage.setItem(
      BOARD_KEY,
      JSON.stringify({
        pins: [{ item: "thread:1", snapshot: snap("Mine"), x: 0, y: 0, pinnedAt: 1 }],
      }),
    );
    link(["thread:1", "thread:7"]);
    vi.mocked(resolveItems).mockResolvedValue({
      items: [
        { item: "thread:1", snapshot: { title: "Mine" } },
        { item: "thread:7", snapshot: { title: "Red Sea" } },
      ],
      rejected: [],
    });
    const { result, onOpen, announce } = render();
    await waitFor(() => expect(result.current.shared.offer).not.toBeNull());
    expect(result.current.shared.offer).toEqual({ shared: 2, fresh: 1, fit: 1 });
    expect(result.current.board.pins).toHaveLength(1);
    act(() => result.current.shared.accept());
    expect(result.current.board.pins.map((p) => p.item)).toEqual(["thread:1", "thread:7"]);
    expect(onOpen).toHaveBeenCalled();
    expect(announce).toHaveBeenCalledWith("Added 1 pin to the board.");
    expect(result.current.shared.offer).toBeNull();
  });

  it("keeps the board as it is when declined", async () => {
    localStorage.setItem(
      BOARD_KEY,
      JSON.stringify({
        pins: [{ item: "thread:1", snapshot: snap("Mine"), x: 0, y: 0, pinnedAt: 1 }],
      }),
    );
    link(["thread:7"]);
    vi.mocked(resolveItems).mockResolvedValue({ items: [], rejected: [] });
    const { result, onOpen } = render();
    await waitFor(() => expect(result.current.shared.offer).not.toBeNull());
    act(() => result.current.shared.decline());
    expect(result.current.board.pins.map((p) => p.item)).toEqual(["thread:1"]);
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("ignores a link that holds no valid id, asking nothing", async () => {
    window.history.replaceState(null, "", "/?board=bm90IGFuIGlk");
    const { result } = render();
    await waitFor(() => expect(window.location.search).toBe(""));
    expect(resolveItems).not.toHaveBeenCalled();
    expect(result.current.shared.offer).toBeNull();
  });

  it("still offers the pins, from their ids, when resolving fails", async () => {
    link(["entity:org:Hamas"]);
    vi.mocked(resolveItems).mockRejectedValue(new Error("offline"));
    const { result } = render();
    await waitFor(() => expect(result.current.board.pins).toHaveLength(1));
    expect(result.current.board.pins[0].snapshot.title).toBe("Hamas");
  });
});
