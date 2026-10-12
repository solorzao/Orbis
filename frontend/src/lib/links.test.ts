import { describe, it, expect } from "vitest";
import {
  ARC_ALTITUDE_SCALE,
  arcApex,
  arcFlows,
  arcPillText,
  arcStroke,
  linkArcs,
  linkEnds,
  actionCountries,
  linkKey,
  linkPairLabel,
  linkedCountries,
  linkTopic,
  toCountryLinks,
  toLinkDetail,
} from "./links";
import type { ApiLink, ApiLinkDetail, ApiNewsArticle } from "./api";
import type { CountryLink } from "@/types/news";

const US = { iso: "US", name: "United States", lat: 39.8, lng: -98.6 };
const IR = { iso: "IR", name: "Iran", lat: 32.4, lng: 53.7 };
const RU = { iso: "RU", name: "Russia", lat: 61.5, lng: 105.3 };
const UA = { iso: "UA", name: "Ukraine", lat: 48.4, lng: 31.2 };

function apiLink(over: Partial<ApiLink> = {}): ApiLink {
  return { a: IR, b: US, n: 41, lift: 1.8, topic: "politics", tone: -0.3, from: "US", ...over };
}

const link = (over: Partial<ApiLink> = {}): CountryLink => toCountryLinks([apiLink(over)])[0];

const COLORS = { coverage: "rgba(180, 190, 255, 0.30)", highlight: "#7fe6ff", flowMs: 6000 };

describe("toCountryLinks", () => {
  it("keeps the ends and numbers, and maps the topic tag to its pill", () => {
    const [l] = toCountryLinks([apiLink({ topic: "environment" })]);
    expect(l).toEqual({ a: IR, b: US, n: 41, lift: 1.8, topic: "Climate", tone: -0.3, from: "US" });
  });

  it("gives a tag outside the six topics no pill (All)", () => {
    expect(toCountryLinks([apiLink({ topic: "sports" })])[0].topic).toBe("All");
  });
});

describe("linkKey", () => {
  it("is the same whichever way round the pair is named", () => {
    expect(linkKey("US", "IR")).toBe(linkKey("IR", "US"));
    expect(linkKey("us", "ir")).toBe("IR-US");
  });
});

describe("linkEnds", () => {
  it("starts where most of the link's stories come from", () => {
    expect(linkEnds(link({ from: "US" }))).toEqual([US, IR]);
    expect(linkEnds(link({ from: "IR" }))).toEqual([IR, US]);
  });

  it("falls back to the code order when the origin is neither end", () => {
    expect(linkEnds(link({ from: "" }))).toEqual([IR, US]);
  });
});

describe("arcStroke", () => {
  it("is 0.16 plus up to 0.5 by the share of the busiest link", () => {
    expect(arcStroke(100, 100)).toBeCloseTo(0.66);
    expect(arcStroke(50, 100)).toBeCloseTo(0.41);
    expect(arcStroke(0, 100)).toBeCloseTo(0.16);
  });

  it("never divides by zero", () => {
    expect(arcStroke(0, 0)).toBeCloseTo(0.16);
  });
});

describe("arcFlows", () => {
  it("flows only with full motion and not in low-power mode", () => {
    expect(arcFlows({ reduced: false, lowPower: false })).toBe(true);
    expect(arcFlows({ reduced: true, lowPower: false })).toBe(false);
    expect(arcFlows({ reduced: false, lowPower: true })).toBe(false);
    expect(arcFlows({ reduced: true, lowPower: true })).toBe(false);
  });
});

describe("linkArcs", () => {
  const links = [link(), link({ a: RU, b: UA, n: 82, lift: 3.1, topic: "conflict", from: "UA" })];

  it("draws each link from its origin, stroked by its stories", () => {
    const arcs = linkArcs(links, { inspected: null, colors: COLORS, flow: false });
    expect(arcs).toHaveLength(2);
    const [usIr, ruUa] = arcs;
    expect(usIr).toMatchObject({
      startLat: US.lat,
      startLng: US.lng,
      endLat: IR.lat,
      endLng: IR.lng,
    });
    expect(ruUa).toMatchObject({
      startLat: UA.lat,
      startLng: UA.lng,
      endLat: RU.lat,
      endLng: RU.lng,
    });
    expect(ruUa.stroke).toBeCloseTo(0.66); // the busiest
    expect(usIr.stroke).toBeCloseTo(0.16 + (41 / 82) * 0.5);
    expect(usIr.link).toBe(links[0]);
    expect(usIr.key).toBe("IR-US");
  });

  it("colours coverage arcs faintly and the inspected link in the highlight", () => {
    const arcs = linkArcs(links, { inspected: linkKey("US", "IR"), colors: COLORS, flow: false });
    expect(arcs[0].color).toBe(COLORS.highlight);
    expect(arcs[1].color).toBe(COLORS.coverage);
    const none = linkArcs(links, { inspected: null, colors: COLORS, flow: false });
    expect(none.map((a) => a.color)).toEqual([COLORS.coverage, COLORS.coverage]);
  });

  it("dashes flow over the token's duration only when motion allows", () => {
    const flowing = linkArcs(links, { inspected: null, colors: COLORS, flow: true })[0];
    expect(flowing).toMatchObject({ dashLength: 0.9, dashGap: 0.1, dashAnimateTime: 6000 });
    const still = linkArcs(links, { inspected: null, colors: COLORS, flow: false })[0];
    expect(still).toMatchObject({ dashLength: 1, dashGap: 0, dashAnimateTime: 0 });
  });
});

describe("arcApex", () => {
  it("is over the great-circle midpoint, at three-globe's curve height", () => {
    // Two points on the equator 90 degrees apart: the midpoint is at 45 degrees.
    const apex = arcApex({ lat: 0, lng: 0 }, { lat: 0, lng: 90 });
    expect(apex.lat).toBeCloseTo(0);
    expect(apex.lng).toBeCloseTo(45);
    // The cubic Bezier's midpoint: (P0 + 3 P1 + 3 P2 + P3) / 8, with the
    // control points at a quarter and three quarters, 1.5x the arc's altitude.
    const alt = ((Math.PI / 2) * ARC_ALTITUDE_SCALE) / 2;
    const r = 1 + 1.5 * alt;
    const c = Math.cos(Math.PI / 8); // each control point is 22.5 degrees off the midpoint
    const expected = (2 * Math.cos(Math.PI / 4) + 6 * r * c) / 8;
    expect(apex.altitude).toBeCloseTo(expected - 1, 6);
  });

  it("is the point itself for a link that has no length", () => {
    expect(arcApex({ lat: 10, lng: 20 }, { lat: 10, lng: 20 })).toEqual({
      lat: 10,
      lng: 20,
      altitude: 0,
    });
  });
});

describe("arcPillText", () => {
  it("says how many stories link the two, from the origin, and their main topic", () => {
    expect(arcPillText(link())).toEqual({
      n: 41,
      text: "stories link United States and Iran, mostly politics",
    });
  });

  it("drops the topic when it is none of the six, and says one story", () => {
    expect(arcPillText(link({ n: 1, topic: "sports", from: "IR" }))).toEqual({
      n: 1,
      text: "story links Iran and United States",
    });
  });
});

describe("linkPairLabel", () => {
  it("names a link by its codes and its countries, from its origin", () => {
    expect(linkPairLabel(link())).toEqual({ short: "US ↔ IR", long: "United States and Iran" });
    expect(linkPairLabel(link({ from: "IR" }))).toEqual({
      short: "IR ↔ US",
      long: "Iran and United States",
    });
  });
});

describe("linkTopic", () => {
  it("is the topic most of the link's stories carry, else the arc's", () => {
    expect(linkTopic({ Politics: 3, Conflict: 9 }, "Politics")).toBe("Conflict");
    expect(linkTopic({}, "Economy")).toBe("Economy");
  });
});

describe("toLinkDetail", () => {
  const article: ApiNewsArticle = {
    id: "s1",
    title: "Talks resume",
    summary: null,
    source_url: "https://example.com/talks",
    source_name: "Reuters",
    source_language: "en",
    published_at: "2026-10-12T11:00:00Z",
    ingested_at: "2026-10-12T11:05:00Z",
    latitude: 38.9,
    longitude: -77,
    country_code: "US",
    region: "Washington, United States",
    topic_tags: ["politics"],
    sentiment_score: -0.1,
    entities: {},
  };

  it("maps the topic mix to topic pills and the stories to articles", () => {
    const api: ApiLinkDetail = {
      a: IR,
      b: US,
      n: 41,
      lift: 1.8,
      topic_mix: { politics: 20, environment: 4, sports: 2 },
      tone: -0.3,
      shared: [{ name: "IAEA", type: "org", n: 9 }],
      themes: ["nuclear talks"],
      articles: [article],
    };
    expect(toLinkDetail(api)).toEqual({
      a: IR,
      b: US,
      n: 41,
      lift: 1.8,
      topicMix: { Politics: 20, Climate: 4 },
      tone: -0.3,
      shared: [{ name: "IAEA", type: "org", n: 9 }],
      themes: ["nuclear talks"],
      articles: [
        {
          id: "s1",
          title: "Talks resume",
          summary: undefined,
          sourceUrl: "https://example.com/talks",
          sourceName: "Reuters",
          publishedAt: "2026-10-12T11:00:00Z",
          latitude: 38.9,
          longitude: -77,
          countryCode: "US",
          region: "Washington, United States",
          topicTags: ["politics"],
          sentimentScore: -0.1,
        },
      ],
    });
  });
});

describe("linkedCountries", () => {
  it("counts the other countries a country's links reach", () => {
    const links = [link(), link({ a: RU, b: US, from: "US" }), link({ a: RU, b: UA, from: "UA" })];
    expect(linkedCountries(links, "US")).toBe(2);
    expect(linkedCountries(links, "ua")).toBe(1);
    expect(linkedCountries(links, "FR")).toBe(0);
    expect(linkedCountries(links, undefined)).toBe(0);
  });
});

describe("actionCountries", () => {
  const dot = (lat: number, lng: number, countryCode?: string) => ({
    id: `${lat}`,
    lat,
    lng,
    size: 1,
    color: "#fff",
    articles: [],
    isCluster: false,
    count: 1,
    topic: "All" as const,
    countryCode,
  });
  const points = [
    dot(48.86, 2.35, "FR"),
    dot(43.3, 5.37, "FR"),
    dot(40.71, -74.0, "US"),
    dot(10, 10),
  ];
  const fly = (lat: number, lng: number) => ({ type: "flyTo" as const, lat, lng });

  it("is the countries of the dots at an answer's places, each once", () => {
    expect(actionCountries([fly(48.86, 2.35), fly(43.3, 5.37)], points)).toEqual(["FR"]);
    expect(actionCountries([fly(48.86, 2.35), fly(40.71, -74.0)], points)).toEqual(["FR", "US"]);
  });

  it("skips places with no dot, or a dot with no country", () => {
    expect(actionCountries([fly(-30, 150), fly(10, 10), fly(40.71, -74.0)], points)).toEqual([
      "US",
    ]);
  });
});
