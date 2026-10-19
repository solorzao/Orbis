import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  SPREAD_DASH_GAP,
  SPREAD_DASH_LENGTH,
  SPREAD_STROKE,
  THREADS_LIMIT,
  fetchThread,
  fetchThreads,
  partOfLabel,
  revealedArcs,
  spreadArcs,
  stopLit,
  threadsStatus,
  toThread,
  toThreadDetail,
  velocityShare,
  type ApiThread,
  type ApiThreadDetail,
  type ThreadPlace,
} from "./threads";

const place = (name: string, lat: number, lng: number, minutes: number) => ({
  lat,
  lng,
  place: name,
  country_code: name.slice(0, 2).toUpperCase(),
  first_seen: new Date(Date.UTC(2026, 9, 18, 12, minutes)).toISOString(),
  n: 2,
});

function apiThread(over: Partial<ApiThread> = {}): ApiThread {
  return {
    id: 7,
    title: "Red Sea shipping attacks",
    synopsis: null,
    status: "developing",
    first_seen: "2026-10-18T06:10:00Z",
    last_seen: "2026-10-18T15:00:00Z",
    n_stories: 14,
    n_sources: 9,
    velocity: 4,
    countries: ["YE", "EG", "NL"],
    places: [
      place("Yemen", 15.5, 48.5, 0),
      place("Egypt", 30.5, 31.5, 20),
      place("Netherlands", 51.5, 4.5, 40),
    ],
    topic: "conflict",
    lead: {
      title: "Ships divert from the Red Sea",
      source_name: "Reuters",
      published_at: "2026-10-18T14:00:00Z",
      image_url: null,
      topic: "conflict",
    },
    ...over,
  };
}

const AURORA = ["rgba(0,212,255,0.25)", "rgba(143,180,255,1)", "rgba(197,170,255,1)"];
const COLORS = { aurora: AURORA, flowMs: 6000 };

describe("toThread", () => {
  it("maps the API's thread to the rail's: status as shown, topic as its pill, the lead", () => {
    const t = toThread(apiThread());
    expect(t).toMatchObject({
      id: 7,
      title: "Red Sea shipping attacks",
      synopsis: null,
      status: "Developing",
      firstSeen: "2026-10-18T06:10:00Z",
      stories: 14,
      outlets: 9,
      velocity: 4,
      countries: ["YE", "EG", "NL"],
      topic: "Conflict",
      lead: { title: "Ships divert from the Red Sea", sourceName: "Reuters", sensitive: true },
    });
    expect(t.places.map((p) => p.place)).toEqual(["Yemen", "Egypt", "Netherlands"]);
    expect(t.places[0]).toEqual({
      lat: 15.5,
      lng: 48.5,
      place: "Yemen",
      countryCode: "YE",
      firstSeen: "2026-10-18T12:00:00.000Z",
      n: 2,
    });
    expect(toThread(apiThread({ status: "emerging", lead: null })).status).toBe("Emerging");
    expect(toThread(apiThread({ lead: null })).lead).toBeNull();
  });
});

describe("toThreadDetail", () => {
  it("adds its key entities, its whole spread and its stories", () => {
    const api: ApiThreadDetail = {
      ...apiThread(),
      entities: [{ name: "Suez Canal Authority", n: 5 }],
      spread: [...apiThread().places, place("Kenya", 0.5, 37.5, 50)],
      timeline: [{ hour: "2026-10-18T12:00:00Z", n: 3, tone: -2.1 }],
      articles: [
        {
          title: "Ships divert from the Red Sea",
          source_name: "Reuters",
          published_at: "2026-10-18T14:00:00Z",
          source_url: "https://example.com/red-sea",
          place: "Yemen",
        },
      ],
    };
    const d = toThreadDetail(api);
    expect(d.entities).toEqual([{ name: "Suez Canal Authority", n: 5 }]);
    expect(d.spread.map((p) => p.place)).toEqual(["Yemen", "Egypt", "Netherlands", "Kenya"]);
    expect(d.articles).toEqual([
      {
        title: "Ships divert from the Red Sea",
        sourceName: "Reuters",
        publishedAt: "2026-10-18T14:00:00Z",
        sourceUrl: "https://example.com/red-sea",
        place: "Yemen",
      },
    ]);
  });
});

describe("fetchThreads and fetchThread", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockResolvedValue(new Response(JSON.stringify([]), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });
  const asked = () => new URL(fetchMock.mock.calls[0][0] as string);

  it("asks for a live window's threads, by topic, 20 of them (the warmed default)", async () => {
    const controller = new AbortController();
    await fetchThreads({ hours: 24, topic: "Politics", signal: controller.signal });
    expect(asked().pathname).toBe("/api/threads");
    expect(Object.fromEntries(asked().searchParams)).toEqual({
      timespan: "24h",
      topic: "Politics",
      limit: String(THREADS_LIMIT),
    });
    expect(fetchMock.mock.calls[0][1]).toEqual({ signal: controller.signal });
    expect(THREADS_LIMIT).toBe(20);
  });

  it("leaves the topic out for All", async () => {
    await fetchThreads({ hours: 168, topic: "All" });
    expect(Object.fromEntries(asked().searchParams)).toEqual({ timespan: "168h", limit: "20" });
  });

  it("asks for one thread, and a page of its stories past the first", async () => {
    fetchMock.mockImplementation(
      async () => new Response(JSON.stringify(apiThread()), { status: 200 }),
    );
    await fetchThread({ id: 7 });
    expect(asked().pathname).toBe("/api/threads/7");
    expect(asked().search).toBe("");
    fetchMock.mockClear();
    await fetchThread({ id: 7, offset: 20 });
    expect(asked().search).toBe("?offset=20");
  });

  it("fails on an error status", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 404, statusText: "Not Found" }));
    await expect(fetchThread({ id: 99 })).rejects.toThrow("404");
  });
});

describe("spreadArcs", () => {
  const spread: ThreadPlace[] = toThread(apiThread()).places;

  it("draws an aurora arc from the first place to each later one, in order of first report", () => {
    const arcs = spreadArcs(7, spread, { colors: COLORS, flow: true });
    expect(arcs).toHaveLength(2);
    expect(arcs.map((a) => [a.startLat, a.startLng, a.endLat, a.endLng])).toEqual([
      [15.5, 48.5, 30.5, 31.5],
      [15.5, 48.5, 51.5, 4.5],
    ]);
    expect(arcs[0]).toMatchObject({
      key: "thread-7-1",
      thread: 7,
      color: AURORA,
      stroke: SPREAD_STROKE,
      dashLength: SPREAD_DASH_LENGTH,
      dashGap: SPREAD_DASH_GAP,
      dashAnimateTime: 6000,
    });
    expect(arcs[0].link).toBeUndefined();
    expect([SPREAD_STROKE, SPREAD_DASH_LENGTH, SPREAD_DASH_GAP]).toEqual([0.55, 0.9, 0.12]);
  });

  it("holds still without flow: solid, no dash, no animation", () => {
    const [arc] = spreadArcs(7, spread, { colors: COLORS, flow: false });
    expect(arc).toMatchObject({ dashLength: 1, dashGap: 0, dashAnimateTime: 0 });
  });

  it("draws nothing for a thread in one place", () => {
    expect(spreadArcs(7, spread.slice(0, 1), { colors: COLORS, flow: true })).toEqual([]);
    expect(spreadArcs(7, [], { colors: COLORS, flow: true })).toEqual([]);
  });
});

describe("a replay's reveal", () => {
  const arcs = spreadArcs(7, toThread(apiThread()).places, { colors: COLORS, flow: true });

  it("shows every arc and stop when not replaying", () => {
    expect(revealedArcs(arcs, null)).toBe(arcs);
    expect([0, 1, 2].map((i) => stopLit(i, null))).toEqual([true, true, true]);
  });

  it("shows the arcs to the places lit so far, keeping each arc the same object", () => {
    expect(revealedArcs(arcs, 1)).toEqual([]);
    expect(revealedArcs(arcs, 2)).toEqual([arcs[0]]);
    expect(revealedArcs(arcs, 2)[0]).toBe(arcs[0]);
    expect(revealedArcs(arcs, 3)).toEqual(arcs);
    expect([0, 1, 2].map((i) => stopLit(i, 2))).toEqual([true, true, false]);
  });
});

describe("threadsStatus", () => {
  const base = { on: true, live: true, threads: [], loading: false, error: false };

  it("says nothing while off or loading, or with threads to show", () => {
    expect(threadsStatus({ ...base, on: false })).toBeNull();
    expect(threadsStatus({ ...base, loading: true })).toBeNull();
    expect(threadsStatus({ ...base, threads: [toThread(apiThread())] })).toBeNull();
  });

  it("says why the rail is empty", () => {
    expect(threadsStatus(base)).toBe("No developing stories in this window");
    expect(threadsStatus({ ...base, error: true })).toBe("Threads unavailable right now");
    expect(threadsStatus({ ...base, live: false })).toBe(
      "Threads follow the live windows: pick 1h, 6h, 24h or 7d",
    );
  });
});

describe("velocityShare", () => {
  it("is a thread's velocity against the fastest listed, as a percentage", () => {
    const threads = [4, 2, 0].map((velocity, i) => toThread(apiThread({ id: i + 1, velocity })));
    expect(threads.map((t) => velocityShare(t, threads))).toEqual([100, 50, 0]);
    const still = [toThread(apiThread({ velocity: 0 }))];
    expect(velocityShare(still[0], still)).toBe(0);
  });
});

describe("partOfLabel", () => {
  const thread = {
    id: 7,
    title: "Red Sea shipping attacks",
    places: ["Yemen", "Suez, Egypt", "Mombasa, Kenya"],
  };

  it("names the thread and up to two other places it reached (names that hold commas)", () => {
    expect(partOfLabel(thread, "Suez, Egypt")).toBe(
      "Part of: Red Sea shipping attacks (also in Yemen and Mombasa, Kenya)",
    );
    expect(partOfLabel(thread, "Paris, France")).toBe(
      "Part of: Red Sea shipping attacks (also in Yemen and Suez, Egypt)",
    );
    expect(partOfLabel({ ...thread, places: ["Yemen", "Suez, Egypt"] }, "Yemen")).toBe(
      "Part of: Red Sea shipping attacks (also in Suez, Egypt)",
    );
    expect(partOfLabel({ ...thread, places: ["Yemen"] }, "Yemen")).toBe(
      "Part of: Red Sea shipping attacks",
    );
  });
});
