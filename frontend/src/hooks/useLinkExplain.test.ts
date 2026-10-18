import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useLinkExplain } from "./useLinkExplain";
import { explainLink, LINK_EXPLAIN_FAILED } from "@/lib/api";
import type { LinkEntry } from "@/types/news";

vi.mock("@/lib/api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/api")>()),
  explainLink: vi.fn(),
}));
const mockExplain = vi.mocked(explainLink);

const US = { iso: "US", name: "United States", lat: 39.5, lng: -99.06 };
const IR = { iso: "IR", name: "Iran", lat: 32.52, lng: 54.29 };

function entry(linkId: string): LinkEntry {
  return {
    linkId,
    link: { a: IR, b: US, n: 41, lift: 1.8, topic: "Politics", tone: -0.3, from: "US" },
    query: {
      startTime: "2026-10-11T12:00:00.000Z",
      endTime: "2026-10-12T12:00:00.000Z",
      live: true,
      hours: 24,
    },
    detail: null,
    detailLoading: false,
    explanation: null,
    explaining: false,
    createdAt: 0,
  };
}

/** An explanation the test answers by hand. */
function deferred() {
  let resolve!: (v: { text: string }) => void;
  let reject!: (e: Error) => void;
  const promise = new Promise<{ text: string }>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  mockExplain.mockReset();
});

describe("useLinkExplain", () => {
  it("asks once per link while a request is in flight, however fast the clicks", async () => {
    const pending = deferred();
    mockExplain.mockReturnValue(pending.promise);
    const update = vi.fn();
    const { result } = renderHook(() => useLinkExplain(update));
    const link = entry("l1");

    // Two clicks in one task: React has not re-rendered, so entry.explaining is still false.
    act(() => {
      void result.current(link);
      void result.current(link);
    });
    expect(mockExplain).toHaveBeenCalledTimes(1);
    expect(mockExplain).toHaveBeenCalledWith({ a: "IR", b: "US", query: link.query });
    expect(update).toHaveBeenCalledWith("l1", { explaining: true });

    await act(async () => pending.resolve({ text: "Talks." }));
    expect(update).toHaveBeenLastCalledWith("l1", {
      explaining: false,
      explanation: { text: "Talks.", ai: true },
    });

    // Answered: it can be asked again.
    mockExplain.mockResolvedValue({ text: "Again." });
    await act(async () => result.current(link));
    expect(mockExplain).toHaveBeenCalledTimes(2);
  });

  it("keeps each link's request to itself", () => {
    mockExplain.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useLinkExplain(vi.fn()));
    act(() => {
      void result.current(entry("l1"));
      void result.current(entry("l2"));
    });
    expect(mockExplain).toHaveBeenCalledTimes(2);
  });

  it("shows a message sent instead as plain text, and a failed request as one", async () => {
    const update = vi.fn();
    const { result } = renderHook(() => useLinkExplain(update));
    mockExplain.mockResolvedValueOnce({ text: "Summary generation failed." });
    await act(async () => result.current(entry("l1")));
    expect(update).toHaveBeenLastCalledWith("l1", {
      explaining: false,
      explanation: { text: "Summary generation failed.", ai: false },
    });

    mockExplain.mockRejectedValueOnce(new Error("API 429"));
    await act(async () => result.current(entry("l1")));
    expect(update).toHaveBeenLastCalledWith("l1", {
      explaining: false,
      explanation: { text: LINK_EXPLAIN_FAILED, ai: false },
    });
  });
});
