import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useState } from "react";
import { act, renderHook } from "@testing-library/react";
import { useRelationDetail } from "./useRelationDetail";
import { REFRESH_MS, useRelations } from "./useRelations";
import { FETCH_DEBOUNCE_MS } from "./useGlobePoints";
import {
  fetchRelationDetail,
  fetchRelations,
  type ApiRelation,
  type ApiRelationDetail,
  type ApiRelations,
} from "@/lib/api";
import { relationKey, toRelation, type Relation } from "@/lib/relations";
import type { RelationEntry } from "@/types/news";
import contract from "../../e2e/relations.contract.json";

// The fetches mocked; the 503 retry as it is.
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  fetchRelations: vi.fn(),
  fetchRelationDetail: vi.fn(),
}));
const mockList = vi.mocked(fetchRelations);
const mockDetail = vi.mocked(fetchRelationDetail);

const LIST = contract.list as ApiRelations;
const [IR_US, FR_US] = LIST.relations as ApiRelation[];

/** A pair's detail with `n` events: the contract's, for that pair. */
const answer = (pair: ApiRelation, n: number): ApiRelationDetail => ({
  ...(contract.detail as ApiRelationDetail),
  a: pair.a,
  b: pair.b,
  n,
});

function deferred() {
  let resolve!: (answer: ApiRelationDetail | null) => void;
  let reject!: (err: Error) => void;
  const promise = new Promise<ApiRelationDetail | null>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const entry = (relationId: string, pair: ApiRelation): RelationEntry => ({
  relationId,
  relation: toRelation(pair),
  filter: "all",
  lens: null,
  detail: null,
  detailLoading: true,
  createdAt: 0,
});

interface Props {
  shownId: string | null;
  /** The layer on (the default) or off. */
  on?: boolean;
}

/** The page's wiring: the layer's list, the open relations, and the one shown. */
function useLayer({ shownId, on = true }: Props) {
  const layer = useRelations("all", on);
  const [queue, setQueue] = useState(() => [entry("ir", IR_US), entry("fr", FR_US)]);
  const shown = queue.find((r) => r.relationId === shownId) ?? null;
  useRelationDetail(shown, layer.answer, { setRelations: setQueue, patch: layer.patch });
  return { layer, queue };
}

const render = () =>
  renderHook((props: Props) => useLayer(props), { initialProps: { shownId: null } as Props });

type View = ReturnType<typeof render>["result"]["current"];
/** A pair's events on its arc, and in its entry's detail. */
const arcN = (v: View, key: string) =>
  v.layer.relations.find((r: Relation) => relationKey(r.a.iso, r.b.iso) === key)?.n;
const entryOf = (v: View, id: string) => v.queue.find((r) => r.relationId === id)!;

const settle = () =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
  });

/** The list drawn (IR–US 312), then `id` shown and its detail answered with `n`. */
async function shownWith(id: "ir" | "fr", n: number) {
  const view = render();
  await settle();
  mockDetail.mockResolvedValueOnce(answer(id === "ir" ? IR_US : FR_US, n));
  view.rerender({ shownId: id });
  await act(async () => {});
  return view;
}

beforeEach(() => {
  vi.useFakeTimers();
  mockList.mockReset();
  mockDetail.mockReset();
  mockList.mockResolvedValue(LIST);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useRelationDetail", () => {
  it("asks for a relation's detail when it is shown, and patches its arc without asking again", async () => {
    const { result } = await shownWith("ir", 318);
    expect(mockDetail).toHaveBeenCalledTimes(1);
    expect(mockDetail).toHaveBeenCalledWith({ a: "IR", b: "US" });
    expect(entryOf(result.current, "ir")).toMatchObject({ detailLoading: false });
    expect(entryOf(result.current, "ir").detail?.relation.n).toBe(318);
    expect(arcN(result.current, "IR-US")).toBe(318);
    // Neither its entry's update nor the patch is a reason to ask again.
    await settle();
    expect(mockDetail).toHaveBeenCalledTimes(1);
  });

  it("says a 404 as text, and a failure as one, the first time", async () => {
    const { result, rerender } = render();
    await settle();
    mockDetail.mockResolvedValueOnce(null).mockRejectedValueOnce(new Error("API 500"));
    rerender({ shownId: "ir" });
    await act(async () => {});
    expect(entryOf(result.current, "ir")).toMatchObject({ detailLoading: false, notFound: true });
    rerender({ shownId: "fr" });
    await act(async () => {});
    expect(entryOf(result.current, "fr")).toMatchObject({
      detailLoading: false,
      detailError: true,
    });
    expect(arcN(result.current, "IR-US")).toBe(312);
  });

  it("loads again, rather than say the old failure, when one that failed is shown again", async () => {
    const { result, rerender } = render();
    await settle();
    mockDetail.mockRejectedValueOnce(new Error("API 500"));
    rerender({ shownId: "ir" });
    await act(async () => {});
    expect(entryOf(result.current, "ir")).toMatchObject({ detailError: true });

    rerender({ shownId: null });
    const next = deferred();
    mockDetail.mockReturnValueOnce(next.promise);
    rerender({ shownId: "ir" });
    expect(entryOf(result.current, "ir")).toMatchObject({
      detail: null,
      detailLoading: true,
      detailError: false,
      notFound: false,
    });
    await act(async () => next.resolve(answer(IR_US, 318)));
    expect(entryOf(result.current, "ir")).toMatchObject({ detailLoading: false });
    expect(entryOf(result.current, "ir").detail?.relation.n).toBe(318);
  });

  it("asks the shown relation again once the layer is back on, not when it goes off", async () => {
    const { rerender } = await shownWith("ir", 318);
    rerender({ shownId: "ir", on: false }); // no list: nothing to agree with
    await settle();
    expect(mockDetail).toHaveBeenCalledTimes(1);

    mockDetail.mockResolvedValueOnce(answer(IR_US, 330));
    rerender({ shownId: "ir", on: true });
    await settle();
    expect(mockDetail).toHaveBeenCalledTimes(2);
  });

  it("asks again when an open relation is shown again, keeping its detail until the new one lands", async () => {
    const { result, rerender } = await shownWith("ir", 318);
    rerender({ shownId: null }); // minimized
    expect(mockDetail).toHaveBeenCalledTimes(1);

    const next = deferred();
    mockDetail.mockReturnValueOnce(next.promise);
    rerender({ shownId: "ir" }); // its pill, or its arc
    expect(mockDetail).toHaveBeenCalledTimes(2);
    expect(entryOf(result.current, "ir")).toMatchObject({ detailLoading: false });
    expect(entryOf(result.current, "ir").detail?.relation.n).toBe(318);
    await act(async () => next.resolve(answer(IR_US, 324)));
    expect(entryOf(result.current, "ir").detail?.relation.n).toBe(324);
    expect(arcN(result.current, "IR-US")).toBe(324);

    // A refetch that fails or finds nothing keeps the detail shown.
    const failures: (() => Promise<ApiRelationDetail | null>)[] = [
      () => Promise.reject(new Error("API 500")),
      async () => null,
    ];
    for (const failing of failures) {
      rerender({ shownId: null });
      mockDetail.mockImplementationOnce(failing);
      rerender({ shownId: "ir" });
      await act(async () => {});
      expect(entryOf(result.current, "ir")).toMatchObject({ detailLoading: false });
      expect(entryOf(result.current, "ir")).not.toMatchObject({ detailError: true });
      expect(entryOf(result.current, "ir")).not.toMatchObject({ notFound: true });
      expect(entryOf(result.current, "ir").detail?.relation.n).toBe(324);
      expect(arcN(result.current, "IR-US")).toBe(324);
    }
  });

  it("asks again for the shown relation when a new list answer lands, and only for it", async () => {
    const { result, rerender } = await shownWith("ir", 318);

    // The refresh draws the list's 312 until the detail asked again says 330.
    mockDetail.mockResolvedValueOnce(answer(IR_US, 330));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(REFRESH_MS);
    });
    await settle();
    expect(mockDetail).toHaveBeenCalledTimes(2);
    expect(mockDetail).toHaveBeenLastCalledWith({ a: "IR", b: "US" });
    expect(entryOf(result.current, "ir").detail?.relation.n).toBe(330);
    expect(arcN(result.current, "IR-US")).toBe(330);

    // Minimized, a refresh asks for nothing (showing it again will).
    rerender({ shownId: null });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(REFRESH_MS);
    });
    await settle();
    expect(mockList).toHaveBeenCalledTimes(3);
    expect(mockDetail).toHaveBeenCalledTimes(2);
  });

  it("puts a late answer for another pair into its own entry and arc, not the shown one's", async () => {
    const { result, rerender } = render();
    await settle();
    const ir = deferred();
    const fr = deferred();
    mockDetail.mockReturnValueOnce(ir.promise).mockReturnValueOnce(fr.promise);
    rerender({ shownId: "ir" });
    rerender({ shownId: "fr" }); // another pair opened before IR–US answered
    await act(async () => fr.resolve(answer(FR_US, 125)));
    await act(async () => ir.resolve(answer(IR_US, 318)));

    expect(entryOf(result.current, "fr").detail?.relation.n).toBe(125);
    expect(entryOf(result.current, "ir").detail?.relation.n).toBe(318);
    expect(arcN(result.current, "FR-US")).toBe(125);
    expect(arcN(result.current, "IR-US")).toBe(318);
  });

  it("drops an earlier answer for the same relation that lands after a later one", async () => {
    const { result, rerender } = render();
    await settle();
    const first = deferred();
    const second = deferred();
    mockDetail.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    rerender({ shownId: "ir" });
    rerender({ shownId: null });
    rerender({ shownId: "ir" });
    await act(async () => second.resolve(answer(IR_US, 330)));
    await act(async () => first.resolve(answer(IR_US, 318)));

    expect(entryOf(result.current, "ir").detail?.relation.n).toBe(330);
    expect(arcN(result.current, "IR-US")).toBe(330);
  });
});
