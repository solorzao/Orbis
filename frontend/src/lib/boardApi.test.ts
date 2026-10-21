import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  MEMO_FAILED,
  MEMO_RATE_LIMITED,
  MEMO_TOO_FEW,
  analyzeBody,
  analyzePins,
  fetchBoardLinks,
  memoParts,
  resolveItems,
} from "./boardApi";
import type { Pin } from "./board";

const mockFetch = vi.fn();

beforeEach(() => {
  mockFetch.mockReset();
  vi.stubGlobal("fetch", mockFetch);
});
afterEach(() => {
  vi.unstubAllGlobals();
});

function json(data: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: () => Promise.resolve(data),
  });
}

const sent = (call = 0) => {
  const [url, init] = mockFetch.mock.calls[call];
  return { path: new URL(url).pathname, init, body: JSON.parse(init.body) };
};

function pin(item: string, title: string, over: Partial<Pin["snapshot"]> = {}): Pin {
  return {
    item,
    snapshot: { title, place: null, lat: null, lng: null, time: null, url: null, ...over },
    x: 0,
    y: 0,
    pinnedAt: 0,
  };
}

describe("resolveItems", () => {
  it("posts the ids in board order and returns each snapshot", async () => {
    mockFetch.mockReturnValue(
      json({
        items: [
          { item: "thread:7", snapshot: { title: "Red Sea" } },
          { item: "place:48:2", snapshot: null },
        ],
      }),
    );
    const out = await resolveItems(["thread:7", "place:48:2"]);
    expect(sent()).toMatchObject({
      path: "/api/board/resolve",
      init: { method: "POST", headers: { "Content-Type": "application/json" } },
      body: { items: ["thread:7", "place:48:2"] },
    });
    expect(out).toEqual({
      items: [
        { item: "thread:7", snapshot: { title: "Red Sea" } },
        { item: "place:48:2", snapshot: null },
      ],
      rejected: [],
    });
  });

  it("drops an id the server refuses (a 422 names its index) and asks again", async () => {
    mockFetch
      .mockReturnValueOnce(json({ detail: "items[1] is not a board item id." }, 422))
      .mockReturnValueOnce(json({ items: [{ item: "thread:7", snapshot: null }] }));
    const out = await resolveItems(["thread:7", "link:FR-ZZ"]);
    expect(sent(1).body).toEqual({ items: ["thread:7"] });
    expect(out).toEqual({
      items: [{ item: "thread:7", snapshot: null }],
      rejected: ["link:FR-ZZ"],
    });
  });

  it("throws on any other failure", async () => {
    mockFetch.mockReturnValue(json({ detail: "items must be distinct." }, 422));
    await expect(resolveItems(["thread:7"])).rejects.toThrow("API 422");
    mockFetch.mockReturnValue(json(null, 500));
    await expect(resolveItems(["thread:7"])).rejects.toThrow("API 500");
  });

  it("asks nothing for no ids", async () => {
    await expect(resolveItems([])).resolves.toEqual({ items: [], rejected: [] });
    expect(mockFetch).not.toHaveBeenCalled();
  });
});

describe("fetchBoardLinks", () => {
  it("posts the ids and keeps the well-formed edges", async () => {
    mockFetch.mockReturnValue(
      json({
        edges: [{ a: "thread:7", b: "place:48:2", kind: "same_place", label: "same place" }],
        co_coverage_checked: true,
      }),
    );
    const out = await fetchBoardLinks(["thread:7", "place:48:2"]);
    expect(sent()).toMatchObject({
      path: "/api/board/links",
      body: { items: ["thread:7", "place:48:2"] },
    });
    expect(out).toEqual({
      edges: [{ a: "thread:7", b: "place:48:2", kind: "same_place", label: "same place" }],
      coCoverageChecked: true,
    });
  });
});

describe("analyzePins", () => {
  const pins = [
    pin("thread:7", "Red Sea shipping attacks", { place: "Yemen", time: "2026-10-20T10:00:00Z" }),
    pin("entity:org:Maersk", "Maersk"),
  ];

  it("sends each pin with its saved title, place and time", () => {
    expect(analyzeBody(pins)).toEqual({
      items: [
        {
          item: "thread:7",
          snapshot: {
            title: "Red Sea shipping attacks",
            place: "Yemen",
            time: "2026-10-20T10:00:00.000Z",
          },
        },
        { item: "entity:org:Maersk", snapshot: { title: "Maersk", place: null, time: null } },
      ],
    });
  });

  it("returns the memo's sections and citations, for the pins it was asked about", async () => {
    mockFetch.mockReturnValue(
      json({
        sections: [
          { heading: "Possible connections", text: "Both concern shipping [1] [2]." },
          { heading: "Contradictions", text: "None stated [1]." },
          { heading: "Open questions", text: "Who reroutes next [2]?" },
        ],
        citations: [
          { n: 1, item: "thread:7" },
          { n: 2, item: "entity:org:Maersk" },
          { n: 99, item: "thread:7" },
        ],
        message: null,
      }),
    );
    const memo = await analyzePins(pins);
    expect(sent()).toMatchObject({ path: "/api/board/analyze", body: analyzeBody(pins) });
    expect(memo).toEqual({
      sections: [
        { heading: "Possible connections", text: "Both concern shipping [1] [2]." },
        { heading: "Contradictions", text: "None stated [1]." },
        { heading: "Open questions", text: "Who reroutes next [2]?" },
      ],
      citations: [
        { n: 1, item: "thread:7" },
        { n: 2, item: "entity:org:Maersk" },
      ],
      message: null,
      items: ["thread:7", "entity:org:Maersk"],
    });
  });

  it("shows the server's message instead of a memo", async () => {
    mockFetch.mockReturnValue(
      json({
        sections: [],
        citations: [],
        message: "AI summaries are paused until 00:00 UTC (daily limit reached).",
      }),
    );
    const memo = await analyzePins(pins);
    expect(memo.message).toBe("AI summaries are paused until 00:00 UTC (daily limit reached).");
    expect(memo.sections).toEqual([]);
  });

  it("says so kindly when rate limited, and when it fails", async () => {
    mockFetch.mockReturnValue(json({ detail: "Rate limit exceeded" }, 429));
    expect((await analyzePins(pins)).message).toBe(MEMO_RATE_LIMITED);
    mockFetch.mockReturnValue(json(null, 500));
    expect((await analyzePins(pins)).message).toBe(MEMO_FAILED);
    mockFetch.mockReturnValue(json({ sections: [], citations: [] }));
    expect((await analyzePins(pins)).message).toBe(MEMO_FAILED);
  });

  it("asks nothing with fewer than two pins", async () => {
    expect((await analyzePins(pins.slice(0, 1))).message).toBe(MEMO_TOO_FEW);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("lets an abort through, so a closed board ignores it", async () => {
    mockFetch.mockReturnValue(Promise.reject(new DOMException("aborted", "AbortError")));
    await expect(analyzePins(pins)).rejects.toThrow("aborted");
  });
});

describe("memoParts", () => {
  it("splits a memo's text at its [n] citations", () => {
    expect(memoParts("Both [1] and [12] say so [3].")).toEqual([
      { text: "Both " },
      { n: 1 },
      { text: " and " },
      { n: 12 },
      { text: " say so " },
      { n: 3 },
      { text: "." },
    ]);
    expect(memoParts("No pins.")).toEqual([{ text: "No pins." }]);
  });
});
