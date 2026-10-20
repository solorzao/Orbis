import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  SPREAD_DASH_GAP,
  SPREAD_DASH_LENGTH,
  SPREAD_STROKE,
  THREADS_LIMIT,
  fetchThread,
  fetchThreads,
  partOfLabel,
  replayAnnouncement,
  revealedArcs,
  spreadView,
  spreadArcs,
  stopLit,
  threadsStatus,
  toThread,
  toThreadArticles,
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

  it("keeps only web (http or https) story URLs: any other is dropped, the story kept", () => {
    const story = (source_url: string) => ({
      title: "A story",
      source_name: "AP",
      published_at: "2026-10-18T14:00:00Z",
      source_url,
      place: "Yemen",
    });
    const urls = toThreadArticles([
      story("javascript:alert(1)"),
      story("data:text/html,x"),
      story("http://example.com/a"),
      story("HTTPS://example.com/b"),
    ]).map((a) => a.sourceUrl);
    expect(urls).toEqual(["", "", "http://example.com/a", "HTTPS://example.com/b"]);
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

describe("spreadView", () => {
  const at = (lat: number, lng: number, place = "") => ({
    lat,
    lng,
    place,
    countryCode: "",
    firstSeen: "2026-10-18T06:10:00Z",
    n: 1,
  });

  it("centres on the middle of the places (on the sphere), high enough to frame them", () => {
    // The Red Sea thread: Yemen, Suez, Rotterdam, Mombasa. Rotterdam is the
    // furthest from their middle, about 36 degrees.
    const view = spreadView([at(15.5, 48.5), at(30.5, 32.5), at(51.5, 4.5), at(-4.5, 39.5)])!;
    expect(view.lat).toBeCloseTo(24, 0);
    expect(view.lng).toBeCloseTo(34.1, 0);
    expect(view.altitude).toBeCloseTo(1.2 + 35.7 / 40, 1);
  });

  it("comes close for one place, and no further than the home view for a wide spread", () => {
    expect(spreadView([at(48.5, 2.5)])).toEqual({ lat: 48.5, lng: 2.5, altitude: 1.5 });
    const wide = spreadView([at(0, -100), at(10, 60)])!;
    expect(wide.altitude).toBe(2.5);
  });

  it("falls back to the first place when the places' middle is nowhere (opposite sides)", () => {
    expect(spreadView([at(0, 0), at(0, 180)])).toEqual({ lat: 0, lng: 0, altitude: 2.5 });
  });

  it("has nowhere to go without places", () => {
    expect(spreadView([])).toBeNull();
  });

  it("stays finite with a place opposite the others' middle (dot rounds below -1)", () => {
    // Two places at A and one at its antipode: their middle is A, the third is
    // exactly opposite, and the rounded dot product comes out under -1.
    for (const [lat, lng] of [
      [10, 20],
      [45, -120],
      [-33, 151],
      [0.5, 179.5],
    ]) {
      const view = spreadView([
        at(lat, lng),
        at(lat, lng),
        at(-lat, lng > 0 ? lng - 180 : lng + 180),
      ])!;
      expect(Number.isFinite(view.altitude), `${lat},${lng}`).toBe(true);
      expect(view.altitude).toBe(2.5); // 180 degrees out: the home view's height
    }
  });

  it("always gives a finite view, wherever the places are (a seeded sweep)", () => {
    let seed = 42;
    const random = () => (seed = (seed * 1664525 + 1013904223) % 2 ** 32) / 2 ** 32;
    const place = () => at(Math.round(random() * 180 - 90), Math.round(random() * 360 - 180));
    for (let i = 0; i < 2000; i++) {
      const n = 1 + Math.floor(random() * 6);
      const places = Array.from({ length: n }, place);
      // Half the time, a place opposite another, the reviewer's NaN case.
      if (i % 2 === 0) {
        const p = places[0];
        places.push(at(-p.lat, p.lng > 0 ? p.lng - 180 : p.lng + 180));
      }
      const view = spreadView(places)!;
      expect(
        [view.lat, view.lng, view.altitude].every(Number.isFinite),
        JSON.stringify(places),
      ).toBe(true);
      expect(view.altitude).toBeGreaterThanOrEqual(1.5);
      expect(view.altitude).toBeLessThanOrEqual(2.5);
    }
  });
});

describe("replayAnnouncement", () => {
  const spread = toThread(apiThread()).places; // Yemen, Egypt, Netherlands

  it("says nothing before a replay", () => {
    expect(replayAnnouncement(spread, "idle")).toBe("");
  });

  it("says once that it replays, not once per place (a thread may reach 30)", () => {
    expect(replayAnnouncement(spread, "started")).toBe("Replaying 3 places");
  });

  it("says when every place is shown (all a reduced-motion replay says)", () => {
    expect(replayAnnouncement(spread, "done")).toBe(
      "Netherlands: place 3 of 3. Every place shown.",
    );
    expect(replayAnnouncement([], "done")).toBe("");
  });
});
