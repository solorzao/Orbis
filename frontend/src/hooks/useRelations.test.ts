import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { REFRESH_MS, useRelations } from "./useRelations";
import { FETCH_DEBOUNCE_MS } from "./useGlobePoints";
import { ApiError, fetchRelations, type ApiRelationDetail, type ApiRelations } from "@/lib/api";
import { toRelationDetail, type RelationDetail, type RelationKind } from "@/lib/relations";
import contract from "../../e2e/relations.contract.json";

// The fetch mocked; ApiError and the 503 retry as they are.
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  fetchRelations: vi.fn(),
}));
const mockFetch = vi.mocked(fetchRelations);

const LIST = contract.list as ApiRelations;
const CONFLICT = contract.list_conflict as ApiRelations;
const DETAIL = toRelationDetail(contract.detail as ApiRelationDetail);
/** IR–US's detail, six events on from the list's (312). */
const FRESH: RelationDetail = { ...DETAIL, relation: { ...DETAIL.relation, n: 318 } };
/** Nothing drawn or loading; `patch` is there whatever the state. */
const IDLE = {
  relations: [],
  lens: null,
  loading: false,
  error: false,
  patch: expect.any(Function),
};

function deferred() {
  let resolve!: (answer: ApiRelations) => void;
  const promise = new Promise<ApiRelations>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

interface Props {
  kind: RelationKind;
  on: boolean;
}

const render = (initialProps: Props) =>
  renderHook(({ kind, on }: Props) => useRelations(kind, on), { initialProps });

const settle = () =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
  });

beforeEach(() => {
  vi.useFakeTimers();
  mockFetch.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useRelations", () => {
  it("fetches nothing while the layer is off (or unavailable)", async () => {
    const { result } = render({ kind: "all", on: false });
    await settle();
    expect(mockFetch).not.toHaveBeenCalled();
    expect(result.current).toEqual(IDLE);
  });

  it("fetches the lens once, every class, 40 at most, once it is on", async () => {
    mockFetch.mockResolvedValue(LIST);
    const { result, rerender } = render({ kind: "all", on: false });
    rerender({ kind: "all", on: true });
    expect(result.current.loading).toBe(true);
    await settle();

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const { signal, ...query } = mockFetch.mock.calls[0][0];
    expect(query).toEqual({ kind: "all", limit: 40 });
    expect(signal).toBeInstanceOf(AbortSignal);
    expect(result.current.loading).toBe(false);
    expect(result.current.relations.map((r) => r.a.iso + r.b.iso)).toEqual([
      "IRUS",
      "FRUS",
      "FRNG",
    ]);
    expect(result.current.lens).toEqual({
      firstDay: "2026-10-15",
      lastDay: "2026-10-21",
      since: "2026-10-15",
    });
  });

  it("refetches for a new class and ignores the first answer when it comes late", async () => {
    const all = deferred();
    const conflict = deferred();
    mockFetch.mockReturnValueOnce(all.promise).mockReturnValueOnce(conflict.promise);
    const { result, rerender } = render({ kind: "all", on: true });
    await settle();
    const firstSignal = mockFetch.mock.calls[0][0].signal!;

    rerender({ kind: "conflict", on: true });
    expect(firstSignal.aborted).toBe(true);
    await settle();
    expect(mockFetch.mock.calls[1][0]).toMatchObject({ kind: "conflict" });
    await act(async () => {
      conflict.resolve(CONFLICT);
      all.resolve(LIST); // late: ignored
    });
    expect(result.current.relations).toHaveLength(1);
    expect(result.current.relations[0].kind).toBe("conflict");
  });

  it("fetches nothing more when only the page re-renders (the lens ignores the timeline)", async () => {
    mockFetch.mockResolvedValue(LIST);
    const { rerender } = render({ kind: "all", on: true });
    await settle();
    rerender({ kind: "all", on: true });
    await settle();
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it("refetches once every 30 minutes while on, keeping the arcs meanwhile", async () => {
    mockFetch.mockResolvedValue(LIST);
    const { result } = render({ kind: "all", on: true });
    await settle();
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(REFRESH_MS).toBe(30 * 60_000);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(REFRESH_MS);
    });
    expect(result.current.relations).toHaveLength(3); // still drawn while it refetches
    await settle();
    expect(mockFetch).toHaveBeenCalledTimes(2);
    expect(result.current).toMatchObject({ loading: false, error: false });
  });

  it("asks once more after a 503, showing no error meanwhile", async () => {
    mockFetch
      .mockRejectedValueOnce(new ApiError(503, "Service Unavailable", 5_000))
      .mockResolvedValueOnce(LIST);
    const { result } = render({ kind: "all", on: true });
    await settle();
    expect(result.current).toMatchObject({ loading: true, error: false });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(mockFetch).toHaveBeenCalledTimes(2);
    expect(result.current).toMatchObject({ loading: false, error: false });
    expect(result.current.relations).toHaveLength(3);
  });

  it("reports an error, and turned off then on again doesn't show the old one", async () => {
    mockFetch.mockRejectedValueOnce(new Error("API 500"));
    const { result, rerender } = render({ kind: "all", on: true });
    await settle();
    expect(result.current).toEqual({ ...IDLE, error: true });

    rerender({ kind: "all", on: false });
    expect(result.current).toEqual(IDLE);
    const next = deferred();
    mockFetch.mockReturnValueOnce(next.promise);
    rerender({ kind: "all", on: true });
    // Not the old error (it would be announced): loading, until the refetch lands.
    expect(result.current).toEqual({ ...IDLE, loading: true });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
      next.resolve(LIST);
    });
    expect(result.current).toMatchObject({ loading: false, error: false });
    expect(result.current.relations).toHaveLength(3);
  });

  it("patches an opened pair's figures from its detail, in place, until the next answer", async () => {
    mockFetch.mockResolvedValue(LIST);
    const { result } = render({ kind: "all", on: true });
    await settle();
    const { patch: patchFn } = result.current;

    act(() => result.current.patch(FRESH));
    expect(result.current.relations.map((r) => [r.a.iso + r.b.iso, r.n])).toEqual([
      ["IRUS", 318],
      ["FRUS", 120],
      ["FRNG", 40],
    ]);
    expect(result.current).toMatchObject({ loading: false, error: false });
    expect(result.current.patch).toBe(patchFn); // stable: page.tsx's callbacks depend on it

    // The next refresh's answer stands as it comes.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(REFRESH_MS);
    });
    await settle();
    expect(result.current.relations[0].n).toBe(312);
  });

  it("doesn't patch a class's answer, even while the next class loads", async () => {
    const all = deferred();
    mockFetch.mockResolvedValueOnce(CONFLICT).mockReturnValueOnce(all.promise);
    const { result, rerender } = render({ kind: "conflict", on: true });
    await settle();
    const before = result.current.relations;
    act(() => result.current.patch(FRESH));
    expect(result.current.relations).toBe(before);

    // Switched to every class: the conflict arcs stay up until it answers, unpatched.
    rerender({ kind: "all", on: true });
    await settle();
    expect(result.current.loading).toBe(true);
    act(() => result.current.patch(FRESH));
    expect(result.current.relations).toBe(before);
    expect(result.current.relations[0].n).toBe(260);

    // Its answer, every class, can be.
    await act(async () => all.resolve(LIST));
    act(() => result.current.patch(FRESH));
    expect(result.current.relations[0].n).toBe(318);
  });

  it("changes nothing while off", async () => {
    const { result } = render({ kind: "all", on: false });
    act(() => result.current.patch(FRESH));
    expect(result.current).toEqual(IDLE);
  });
});
