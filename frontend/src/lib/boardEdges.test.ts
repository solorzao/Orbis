import { describe, it, expect } from "vitest";
import {
  CLOSE_IN_TIME_MS,
  EDGE_BOW,
  boardArcs,
  boardEdges,
  boardMirror,
  closeInTimeEdges,
  layoutEdges,
  pinEdges,
  toBoardLinks,
  type BoardEdge,
} from "./boardEdges";
import type { Pin, PinSnapshot } from "./board";

const UUID_A = "4f6c2a7e-1d2b-4c3d-9e8f-0a1b2c3d4e5f";
const UUID_B = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d";
const T0 = Date.parse("2026-10-20T10:00:00Z");
const iso = (ms: number) => new Date(ms).toISOString();

function pin(item: string, snapshot: Partial<PinSnapshot> = {}): Pin {
  return {
    item,
    snapshot: {
      title: item,
      place: null,
      lat: null,
      lng: null,
      time: null,
      url: null,
      ...snapshot,
    },
    x: 0.5,
    y: 0.5,
    pinnedAt: 1,
  };
}

const ARTICLE = pin(`article:${UUID_A}`, { lat: 48.85, lng: 2.35, time: iso(T0) });
const OTHER = pin(`article:${UUID_B}`, { lat: 51.5, lng: -0.1, time: iso(T0 + 45 * 60_000) });
const THREAD = pin("thread:7", { lat: 15.5, lng: 48.5, time: iso(T0 + 10 * 60_000) });
const ENTITY = pin("entity:person:Emmanuel Macron", { lat: 48.5, lng: 2.5 });
const LINK = pin("link:FR-GB");

describe("the server's edges (/api/board/links)", () => {
  it("keeps well-formed edges and says whether co-coverage was checked", () => {
    expect(
      toBoardLinks({
        edges: [
          { a: ARTICLE.item, b: THREAD.item, kind: "same_thread", label: "same thread" },
          { a: ARTICLE.item, b: LINK.item, kind: "linked", label: "nope" },
          { a: ARTICLE.item, b: 5, kind: "same_place", label: "same place" },
          { a: ARTICLE.item, b: ENTITY.item, kind: "shared_entity", label: "shared:‮ Macron" },
        ],
        co_coverage_checked: false,
      }),
    ).toEqual({
      edges: [
        { a: ARTICLE.item, b: THREAD.item, kind: "same_thread", label: "same thread" },
        { a: ARTICLE.item, b: ENTITY.item, kind: "shared_entity", label: "shared: Macron" },
      ],
      coCoverageChecked: false,
    });
    expect(toBoardLinks(null)).toEqual({ edges: [], coCoverageChecked: false });
  });
});

describe("close in time", () => {
  it("joins two stories published within two hours, saying how far apart", () => {
    expect(closeInTimeEdges([ARTICLE, THREAD, OTHER])).toEqual([
      { a: ARTICLE.item, b: OTHER.item, kind: "close_in_time", label: "45 min apart" },
    ]);
  });

  it("says hours past the hour, and nothing past two hours or without a time", () => {
    const late = pin(`article:${UUID_B}`, { time: iso(T0 + 90 * 60_000) });
    expect(closeInTimeEdges([ARTICLE, late])[0].label).toBe("1.5 h apart");
    const far = pin(`article:${UUID_B}`, { time: iso(T0 + CLOSE_IN_TIME_MS + 1) });
    expect(closeInTimeEdges([ARTICLE, far])).toEqual([]);
    const timeless = pin(`article:${UUID_B}`);
    expect(closeInTimeEdges([ARTICLE, timeless])).toEqual([]);
  });
});

describe("the board's edges", () => {
  const server: BoardEdge[] = [
    { a: ARTICLE.item, b: ENTITY.item, kind: "shared_entity", label: "shared: Emmanuel Macron" },
    { a: ARTICLE.item, b: THREAD.item, kind: "same_thread", label: "same thread" },
    { a: "thread:99", b: ARTICLE.item, kind: "same_thread", label: "same thread" },
  ];

  it("adds close in time to the server's, for pins still on the board, by pins then kind", () => {
    const pins = [ARTICLE, THREAD, ENTITY, OTHER];
    expect(boardEdges(server, pins).map((e) => `${e.a}>${e.b}:${e.kind}`)).toEqual([
      `${ARTICLE.item}>${THREAD.item}:same_thread`,
      `${ARTICLE.item}>${ENTITY.item}:shared_entity`,
      `${ARTICLE.item}>${OTHER.item}:close_in_time`,
    ]);
  });

  it("lists each pin's edges under it, naming the other pin by its number", () => {
    const pins = [ARTICLE, THREAD, ENTITY];
    const by = pinEdges(pins, boardEdges(server, pins));
    expect(by.get(ARTICLE.item)).toEqual([
      { other: THREAD.item, n: 2, kind: "same_thread", label: "same thread" },
      { other: ENTITY.item, n: 3, kind: "shared_entity", label: "shared: Emmanuel Macron" },
    ]);
    expect(by.get(ENTITY.item)).toEqual([
      { other: ARTICLE.item, n: 1, kind: "shared_entity", label: "shared: Emmanuel Macron" },
    ]);
    expect(by.get(THREAD.item)).toHaveLength(1);
  });
});

describe("the edge layout", () => {
  const centres = new Map([
    ["a", { x: 100, y: 100 }],
    ["b", { x: 300, y: 100 }],
    ["c", { x: 100, y: 300 }],
  ]);

  it("curves each edge between its cards' centres, its label at the curve's middle", () => {
    const [edge] = layoutEdges(centres, [
      { a: "a", b: "b", kind: "same_thread", label: "same thread" },
    ]);
    expect(edge.key).toBe("a|b|same_thread");
    expect(edge.d).toMatch(/^M100 100 Q200 [\d.-]+ 300 100$/);
    expect(edge.x).toBe(200);
    // Bowed off the straight line, the label sits off it too, by half the bow.
    const bow = Number(edge.d.split(" ")[3]) - 100;
    expect(bow).not.toBe(0);
    expect(edge.y).toBeCloseTo(100 + bow / 2, 6);
  });

  it("bows the edges of one pair apart, so each label shows", () => {
    const laid = layoutEdges(centres, [
      { a: "a", b: "b", kind: "same_thread", label: "same thread" },
      { a: "a", b: "b", kind: "shared_entity", label: "shared: X" },
      { a: "a", b: "c", kind: "co_covered", label: "covered together: A and B" },
    ]);
    expect(laid).toHaveLength(3);
    expect(Math.abs(laid[0].y - laid[1].y)).toBeGreaterThan(20);
    // A pair with one edge bows by EDGE_BOW: its label half that off the chord's middle.
    expect(laid[2].y).toBe(200);
    expect(Math.abs(laid[2].x - 100)).toBeCloseTo(EDGE_BOW / 2, 6);
  });

  it("skips an edge whose card isn't laid out", () => {
    expect(
      layoutEdges(centres, [{ a: "a", b: "z", kind: "same_place", label: "same place" }]),
    ).toEqual([]);
  });
});

describe("the globe's mirror of the board", () => {
  const pins = [ARTICLE, THREAD, ENTITY, LINK];
  const edges = boardEdges(
    [
      { a: ARTICLE.item, b: THREAD.item, kind: "same_thread", label: "same thread" },
      { a: ARTICLE.item, b: THREAD.item, kind: "shared_entity", label: "shared: X" },
      { a: ARTICLE.item, b: ENTITY.item, kind: "shared_entity", label: "shared: Macron" },
      { a: ARTICLE.item, b: LINK.item, kind: "co_covered", label: "covered together: F and G" },
    ],
    pins,
  );

  it("highlights each pinned place once (its 1° cell)", () => {
    const mirror = boardMirror(pins, edges);
    expect(mirror.places.map((p) => [p.lat, p.lng])).toEqual([
      [48.85, 2.35],
      [15.5, 48.5],
    ]);
  });

  it("draws one arc per pair of pins in different places, the strongest kind", () => {
    const { arcs } = boardMirror(pins, edges);
    expect(arcs).toEqual([
      {
        key: `board-${ARTICLE.item}|${THREAD.item}`,
        kind: "same_thread",
        startLat: 48.85,
        startLng: 2.35,
        endLat: 15.5,
        endLng: 48.5,
      },
    ]);
  });

  it("styles the arcs with the board's colour, same thread flowing when motion allows", () => {
    const colors = { thread: "#8b9cff", start: "rgba(139,156,255,0.25)", other: "o", flowMs: 6000 };
    const { arcs } = boardMirror(pins, edges);
    const [flowing] = boardArcs(arcs, { colors, flow: true });
    expect(flowing).toMatchObject({
      key: arcs[0].key,
      color: [colors.start, colors.thread],
      dashGap: 0.12,
      dashAnimateTime: 6000,
    });
    const [still] = boardArcs(arcs, { colors, flow: false });
    expect(still).toMatchObject({ dashGap: 0, dashAnimateTime: 0 });
    const other = boardArcs([{ ...arcs[0], kind: "co_covered" }], { colors, flow: true })[0];
    expect(other).toMatchObject({ color: "o", dashGap: 0 });
  });
});
