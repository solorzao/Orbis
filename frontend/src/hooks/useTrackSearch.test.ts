import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useTrackSearch } from "./useTrackSearch";
import { SEARCH_DEBOUNCE_MS, fetchSearch, type ApiSearchResults } from "@/lib/entities";

vi.mock("@/lib/entities", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/entities")>()),
  fetchSearch: vi.fn(),
}));
const mockSearch = vi.mocked(fetchSearch);

const results = (name: string): ApiSearchResults => ({
  people: [{ type: "person", name, n: 3, capped: false }],
  orgs: [],
  threads: [],
});

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (err: Error) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const render = (q: string) =>
  renderHook(({ q }: { q: string }) => useTrackSearch(q), { initialProps: { q } });

const wait = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });

beforeEach(() => {
  vi.useFakeTimers();
  mockSearch.mockReset();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("useTrackSearch", () => {
  it("asks nothing for fewer than two characters", async () => {
    const { result } = render("M");
    await wait(SEARCH_DEBOUNCE_MS * 2);
    expect(mockSearch).not.toHaveBeenCalled();
    expect(result.current).toEqual({ results: null, loading: false, error: false });
  });

  it("asks once typing pauses for 200 ms, with the cleaned query", async () => {
    mockSearch.mockResolvedValue(results("Emmanuel Macron"));
    const { result, rerender } = render("Ma");
    rerender({ q: "Mac" });
    rerender({ q: " Macron​ " });
    expect(result.current.loading).toBe(true);
    await wait(SEARCH_DEBOUNCE_MS - 1);
    expect(mockSearch).not.toHaveBeenCalled();
    await wait(1);
    expect(mockSearch).toHaveBeenCalledTimes(1);
    expect(mockSearch.mock.calls[0][0]).toBe("Macron");
    expect(result.current.results?.people[0].name).toBe("Emmanuel Macron");
    expect(result.current.loading).toBe(false);
  });

  it("aborts a superseded request and never shows its answer", async () => {
    const first = deferred<ApiSearchResults>();
    const second = deferred<ApiSearchResults>();
    mockSearch.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const { result, rerender } = render("Mac");
    await wait(SEARCH_DEBOUNCE_MS);
    const signal = mockSearch.mock.calls[0][1]!;
    rerender({ q: "Merz" });
    expect(signal.aborted).toBe(true);
    await wait(SEARCH_DEBOUNCE_MS);
    await act(async () => first.resolve(results("Emmanuel Macron")));
    expect(result.current.results).toBeNull();
    await act(async () => second.resolve(results("Friedrich Merz")));
    expect(result.current.results?.people[0].name).toBe("Friedrich Merz");
  });

  it("shows only the current query's results: none while the next loads", async () => {
    mockSearch.mockResolvedValueOnce(results("Emmanuel Macron"));
    const { result, rerender } = render("Mac");
    await wait(SEARCH_DEBOUNCE_MS);
    expect(result.current.results).not.toBeNull();
    mockSearch.mockReturnValueOnce(new Promise(() => {}));
    rerender({ q: "Merz" });
    expect(result.current).toEqual({ results: null, loading: true, error: false });
  });

  it("says when the search failed", async () => {
    mockSearch.mockRejectedValue(new Error("API 500"));
    const { result } = render("Macron");
    await wait(SEARCH_DEBOUNCE_MS);
    expect(result.current).toEqual({ results: null, loading: false, error: true });
  });
});
