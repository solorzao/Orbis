import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  CONSTELLATION,
  ENTITY_STROKE,
  FOCUS_DIM_OPACITY,
  PLACES_SHOWN,
  constellation,
  countLabel,
  dimColor,
  fetchEntity,
  fetchSearch,
  focusArcs,
  focusCentre,
  focusLayer,
  focusRadius,
  pivotType,
  rampSince,
  searchAnnouncement,
  searchPlaces,
  searchQuery,
  shortDate,
  toDossier,
  toSearchResults,
  trendLabel,
  typeLabel,
  type ApiEntityDossier,
  type CoMention,
  type EntityPlace,
} from "./entities";
import { ApiError } from "./api";
import type { GlobePoint } from "@/types/news";

function dot(name: string | undefined, count: number, lat = 10, lng = 20): GlobePoint {
  return {
    id: `${name}-${lat}`,
    lat,
    lng,
    size: 1,
    color: "#ab9dff",
    articles: [],
    isCluster: count > 1,
    count,
    locationName: name,
    topic: "Politics",
  };
}

function apiDossier(over: Partial<ApiEntityDossier> = {}): ApiEntityDossier {
  return {
    name: "Emmanuel Macron",
    type: "person",
    counts: { h24: 12, d7: 140 },
    trend: 1.5,
    capped: false,
    cap: 2000,
    countries: [
      { country_code: "FR", n: 90 },
      { country_code: "DE", n: 20 },
    ],
    places: [
      { lat: 48.85, lng: 2.35, place: "Paris, France", country_code: "FR", n: 60, tone: -0.1 },
      { lat: 52.52, lng: 13.4, place: "Berlin, Germany", country_code: "DE", n: 15, tone: 0.2 },
    ],
    timeline: [
      { t: "2026-10-14T12:00:00Z", n: 10 },
      { t: "2026-10-15T12:00:00Z", n: 30 },
    ],
    co_mentions: [{ name: "European Union", n: 30, types: ["org"] }],
    headlines: [
      {
        title: "Macron meets Scholz in Berlin",
        source_name: "Reuters",
        published_at: "2026-10-20T10:00:00Z",
        source_url: "https://example.com/a",
        place: "Berlin, Germany",
      },
      {
        title: "A story with a bad link",
        source_name: "Mystery",
        published_at: "2026-10-20T09:00:00Z",
        source_url: "javascript:alert(1)",
        place: "Paris, France",
      },
    ],
    since: "2026-10-12T00:00:00Z",
    ...over,
  };
}

describe("searchQuery", () => {
  it("trims and collapses spaces", () => {
    expect(searchQuery("  Emmanuel   Macron ")).toBe("Emmanuel Macron");
  });

  it("drops invisible characters, as the server does", () => {
    expect(searchQuery("Ma​cron⁠")).toBe("Macron");
  });
});

describe("fetchSearch and fetchEntity", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });
  const asked = () => new URL(fetchMock.mock.calls[0][0] as string);

  it("asks /api/search for the query, with the abort signal", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ people: [], orgs: [], threads: [] }), { status: 200 }),
    );
    const controller = new AbortController();
    await fetchSearch("Macron", controller.signal);
    expect(asked().pathname).toBe("/api/search");
    expect(asked().searchParams.get("q")).toBe("Macron");
    expect(fetchMock.mock.calls[0][1]).toEqual({ signal: controller.signal });
  });

  it("asks for a person's or organisation's week, the name as one path segment", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify(apiDossier()), { status: 200 }));
    await fetchEntity({ type: "org", name: "AT&T / Verizon?" });
    expect(asked().pathname).toBe(`/api/entities/org/${encodeURIComponent("AT&T / Verizon?")}`);
    expect(asked().searchParams.get("timespan")).toBe("168h");
  });

  it("says an unknown name is not found (404) with the status", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 404, statusText: "Not Found" }));
    const err = await fetchEntity({ type: "person", name: "Nobody" }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
  });
});

describe("toSearchResults", () => {
  it("keeps people, organisations and threads, the same name in both groups", () => {
    const r = toSearchResults({
      people: [{ type: "person", name: "Hamas", n: 3, capped: false }],
      orgs: [{ type: "org", name: "Hamas", n: 100, capped: true }],
      threads: [{ id: 7, title: "Red Sea shipping attacks" }],
    });
    expect(r.people).toEqual([{ type: "person", name: "Hamas", n: 3, capped: false }]);
    expect(r.orgs).toEqual([{ type: "org", name: "Hamas", n: 100, capped: true }]);
    expect(r.threads).toEqual([{ id: 7, title: "Red Sea shipping attacks" }]);
  });

  it("tolerates missing groups", () => {
    expect(toSearchResults({} as never)).toEqual({ people: [], orgs: [], threads: [] });
  });
});

describe("searchPlaces", () => {
  const points = [
    dot("Paris, France", 5, 48.8, 2.3),
    dot("Paris, Texas, United States", 2, 33.6, -95.5),
    dot("Comparison Island", 9, 1, 1),
    dot("Saint-Paris, France", 1, 45, 3),
    dot("London, United Kingdom", 3, 51.5, -0.1),
    dot(undefined, 50, 0, 0),
  ];

  it("finds places by the start of their name, then of a word, then anywhere, busiest first", () => {
    expect(searchPlaces(points, "par").map((p) => p.locationName)).toEqual([
      "Paris, France",
      "Paris, Texas, United States",
      "Saint-Paris, France",
      "Comparison Island",
    ]);
  });

  it("ignores case and accents", () => {
    const zurich = dot("Zürich, Switzerland", 4, 47.4, 8.5);
    expect(searchPlaces([zurich], "ZURICH")).toEqual([zurich]);
    expect(searchPlaces([dot("Sao Paulo, Brazil", 2)], "são")).toHaveLength(1);
  });

  it("shows at most five, one per name", () => {
    const many = Array.from({ length: 9 }, (_, i) => dot(`Place ${i}`, i + 1, i, i));
    many.push(dot("Place 8", 1, 80, 80)); // the same name again, quieter
    const found = searchPlaces(many, "place");
    expect(found).toHaveLength(PLACES_SHOWN);
    expect(PLACES_SHOWN).toBe(5);
    expect(found.map((p) => p.locationName)).toEqual([
      "Place 8",
      "Place 7",
      "Place 6",
      "Place 5",
      "Place 4",
    ]);
    expect(found[0].lat).toBe(8);
  });

  it("finds nothing for an empty query or a place with no name", () => {
    expect(searchPlaces(points, "  ")).toEqual([]);
    expect(searchPlaces(points, "zzz")).toEqual([]);
  });
});

describe("labels", () => {
  it("says a capped count is at least n", () => {
    expect(countLabel(12, false)).toBe("12");
    expect(countLabel(100, true)).toBe("100+");
    expect(countLabel(2140, false)).toBe("2,140");
  });

  it("names the type", () => {
    expect(typeLabel("person")).toBe("Person");
    expect(typeLabel("org")).toBe("Organisation");
  });

  it("writes a short UTC date", () => {
    expect(shortDate("2026-10-18T23:30:00Z")).toBe("18 Oct");
  });

  it("writes the trend as a ratio, or a dash when there was nothing before", () => {
    expect(trendLabel(1.5)).toBe("1.5×");
    expect(trendLabel(0.25)).toBe("0.25×");
    expect(trendLabel(null)).toBe("–");
  });
});

describe("rampSince", () => {
  const now = Date.parse("2026-10-20T12:00:00Z");

  it("gives the start while it is under seven days ago", () => {
    expect(rampSince("2026-10-18T06:00:00Z", now)).toBe("2026-10-18T06:00:00Z");
  });

  it("gives nothing once a full week is held, or with no start", () => {
    expect(rampSince("2026-10-13T11:59:00Z", now)).toBeNull();
    expect(rampSince(null, now)).toBeNull();
  });
});

describe("toDossier", () => {
  it("maps the API's dossier to the app's", () => {
    const d = toDossier(apiDossier());
    expect(d).toMatchObject({
      name: "Emmanuel Macron",
      type: "person",
      h24: 12,
      d7: 140,
      trend: 1.5,
      capped: false,
      cap: 2000,
      countries: 2,
      since: "2026-10-12T00:00:00Z",
    });
    expect(d.places[0]).toEqual({
      lat: 48.85,
      lng: 2.35,
      place: "Paris, France",
      countryCode: "FR",
      n: 60,
      tone: -0.1,
    });
    expect(d.coMentions).toEqual([{ name: "European Union", n: 30, types: ["org"] }]);
    expect(d.timeline).toEqual([
      { t: "2026-10-14T12:00:00Z", n: 10 },
      { t: "2026-10-15T12:00:00Z", n: 30 },
    ]);
  });

  it("keeps only web links: a headline with any other keeps its text, without a link", () => {
    const d = toDossier(apiDossier());
    expect(d.headlines.map((h) => h.sourceUrl)).toEqual(["https://example.com/a", ""]);
    expect(d.headlines[1]).toMatchObject({
      title: "A story with a bad link",
      sourceName: "Mystery",
    });
  });

  it("leaves untyped co-mentions untrackable", () => {
    const d = toDossier(apiDossier({ co_mentions: [{ name: "Red Sea", n: 4 } as never] }));
    expect(d.coMentions[0].types).toEqual([]);
  });
});

describe("pivotType", () => {
  const m = (types: CoMention["types"]): CoMention => ({ name: "X", n: 1, types });
  it("tracks a name as its one type, the current type when it has both, or not at all", () => {
    expect(pivotType(m(["org"]), "person")).toBe("org");
    expect(pivotType(m(["person", "org"]), "org")).toBe("org");
    expect(pivotType(m(["person", "org"]), "person")).toBe("person");
    expect(pivotType(m([]), "person")).toBeNull();
  });
});

describe("searchAnnouncement", () => {
  it("counts each group, in plain words", () => {
    expect(searchAnnouncement({ places: 2, people: 1, orgs: 3, threads: 1 })).toBe(
      "2 places, 1 person, 3 organisations and 1 thread",
    );
    expect(searchAnnouncement({ places: 1, people: 2, orgs: 0, threads: 0 })).toBe(
      "1 place and 2 people",
    );
    expect(searchAnnouncement({ places: 0, people: 0, orgs: 1, threads: 2 })).toBe(
      "1 organisation and 2 threads",
    );
  });

  it("says when nothing matched", () => {
    expect(searchAnnouncement({ places: 0, people: 0, orgs: 0, threads: 0 })).toBe("No matches");
  });
});

const places: EntityPlace[] = [
  { lat: 48.85, lng: 2.35, place: "Paris, France", countryCode: "FR", n: 60, tone: -0.1 },
  { lat: 52.52, lng: 13.4, place: "Berlin, Germany", countryCode: "DE", n: 15, tone: 0.2 },
  { lat: -33.9, lng: 18.4, place: "Cape Town, South Africa", countryCode: "ZA", n: 5, tone: 0 },
];

describe("focusCentre", () => {
  it("is the mention-weighted middle of the places, nearest the busiest", () => {
    const c = focusCentre(places)!;
    expect(c.lat).toBeGreaterThan(30);
    expect(c.lat).toBeLessThan(48.85);
    // Paris has four times Berlin's stories: the centre sits much nearer Paris.
    expect(c.lng).toBeGreaterThan(2.35);
    expect(c.lng).toBeLessThan(10);
  });

  it("is the place itself for one place, and nothing for none", () => {
    expect(focusCentre([places[0]])).toEqual({ lat: 48.85, lng: 2.35 });
    expect(focusCentre([])).toBeNull();
  });
});

describe("focusArcs", () => {
  const colors = {
    highlight: "rgba(127,230,255,1)",
    start: "rgba(127,230,255,0.25)",
    flowMs: 6000,
  };

  it("runs an arc from the centre to each place, stroked by its stories", () => {
    const centre = { lat: 40, lng: 5 };
    const arcs = focusArcs("Emmanuel Macron", centre, places, { colors, flow: true });
    expect(arcs).toHaveLength(3);
    expect(arcs[0]).toMatchObject({
      startLat: 40,
      startLng: 5,
      endLat: 48.85,
      endLng: 2.35,
      color: [colors.start, colors.highlight],
      dashGap: 0.12,
      dashAnimateTime: 6000,
    });
    expect(arcs[0].stroke).toBeCloseTo(ENTITY_STROKE.active);
    expect(arcs[2].stroke).toBeGreaterThanOrEqual(ENTITY_STROKE.base);
    expect(arcs[2].stroke).toBeLessThan(arcs[0].stroke);
    expect(new Set(arcs.map((a) => a.key)).size).toBe(3);
    expect(arcs.every((a) => a.link === undefined && a.thread === undefined)).toBe(true);
  });

  it("holds still when motion is off", () => {
    const [arc] = focusArcs("X", { lat: 0, lng: 0 }, places, { colors, flow: false });
    expect(arc).toMatchObject({ dashLength: 1, dashGap: 0, dashAnimateTime: 0 });
  });

  it("draws no arc to a place at the centre itself", () => {
    expect(focusArcs("X", { lat: 48.85, lng: 2.35 }, [places[0]], { colors, flow: true })).toEqual(
      [],
    );
  });
});

describe("focusLayer", () => {
  const paris = dot("Paris, France", 5, 48.8566, 2.3522);
  const london = dot("London, United Kingdom", 3, 51.5074, -0.1278);

  it("keeps the dots, adds a stand-in for a place without one, and sizes the places by n", () => {
    const layer = focusLayer([paris, london], places);
    expect(layer.dots.slice(0, 2)).toEqual([paris, london]);
    expect(layer.dots.map((d) => d.locationName)).toEqual([
      "Paris, France",
      "London, United Kingdom",
      "Berlin, Germany",
      "Cape Town, South Africa",
    ]);
    expect(layer.n(paris)).toBe(60);
    expect(layer.n(london)).toBeNull();
    expect(layer.n(layer.dots[2])).toBe(15);
    expect(layer.maxN).toBe(60);
  });
});

describe("focusRadius and dimColor", () => {
  it("grows with the place's share of the busiest", () => {
    expect(focusRadius(60, 60)).toBeGreaterThan(focusRadius(15, 60));
    expect(focusRadius(1, 60)).toBeGreaterThan(0);
  });

  it("dims a dot's colour to the focus opacity", () => {
    expect(dimColor("#ab9dff")).toBe(`rgba(171,157,255,${FOCUS_DIM_OPACITY})`);
  });
});

describe("constellation", () => {
  const co = (n: number): CoMention[] =>
    Array.from({ length: n }, (_, i) => ({
      name: i === 0 ? "A very long organisation name indeed" : `Name ${i}`,
      n: 40 - i * 2,
      types: i % 3 === 2 ? [] : ["org"],
    }));

  it("lays out at most 15 names around the entity, inside the drawing", () => {
    const nodes = constellation(co(20));
    expect(nodes).toHaveLength(CONSTELLATION.max);
    for (const node of nodes) {
      expect(node.x - node.r).toBeGreaterThanOrEqual(0);
      expect(node.x + node.r).toBeLessThanOrEqual(CONSTELLATION.width);
      expect(node.y - node.r).toBeGreaterThanOrEqual(0);
      expect(node.y + node.r).toBeLessThanOrEqual(CONSTELLATION.height);
    }
  });

  it("sizes each by its stories and shortens long labels", () => {
    const nodes = constellation(co(6));
    expect(nodes[0].r).toBeGreaterThan(nodes[5].r);
    expect(nodes[0].label).toBe("A very long…");
    expect(nodes[1].label).toBe("Name 1");
    expect(nodes[0].name).toBe("A very long organisation name indeed");
  });

  it("puts the busiest five on the inner ring", () => {
    const nodes = constellation(co(10));
    const dist = (i: number) =>
      Math.hypot(
        (nodes[i].x - CONSTELLATION.cx) / CONSTELLATION.outer.rx,
        (nodes[i].y - CONSTELLATION.cy) / CONSTELLATION.outer.ry,
      );
    expect(dist(0)).toBeLessThan(dist(5));
    expect(dist(4)).toBeLessThan(dist(9));
  });

  it("draws nothing without names", () => {
    expect(constellation([])).toEqual([]);
  });
});
