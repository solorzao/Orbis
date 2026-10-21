import { describe, it, expect, vi } from "vitest";
import {
  BOARD_KEY,
  MAX_PINS,
  SHARE_MAX_CHARS,
  addPin,
  applyResolved,
  articleItem,
  boardFromJson,
  canonicalName,
  decodeShare,
  encodeShare,
  entityItem,
  fallbackSnapshot,
  keyMove,
  linkItem,
  mergePins,
  mergePlan,
  movePin,
  nextSlot,
  parseItem,
  pinKindLabel,
  placeItem,
  positionWords,
  readBoard,
  removePin,
  shareUrl,
  sharedEntries,
  threadItem,
  toSnapshot,
  writeBoard,
  type BoardState,
  type Pin,
  type PinSnapshot,
} from "./board";

const UUID = "4f6c2a7e-1d2b-4c3d-9e8f-0a1b2c3d4e5f";
const OTHER = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d";

const snap = (title: string, over: Partial<PinSnapshot> = {}): PinSnapshot => ({
  title,
  place: null,
  lat: null,
  lng: null,
  time: null,
  url: null,
  ...over,
});

const pin = (item: string, over: Partial<Pin> = {}): Pin => ({
  item,
  snapshot: snap(item),
  x: 0.5,
  y: 0.5,
  pinnedAt: 1,
  ...over,
});

const board = (...pins: Pin[]): BoardState => ({ pins });

describe("item ids (the backend's board.parse_item rules)", () => {
  it.each([
    [`article:${UUID}`, { kind: "article", id: UUID }],
    ["place:48:2", { kind: "place", lat: 48, lng: 2 }],
    ["place:-34:-59", { kind: "place", lat: -34, lng: -59 }],
    ["place:0:0", { kind: "place", lat: 0, lng: 0 }],
    ["place:90:180", { kind: "place", lat: 90, lng: 180 }],
    ["place:-90:-180", { kind: "place", lat: -90, lng: -180 }],
    ["link:FR-US", { kind: "link", a: "FR", b: "US" }],
    ["thread:7", { kind: "thread", id: "7" }],
    ["thread:9223372036854775807", { kind: "thread", id: "9223372036854775807" }],
    ["entity:person:Emmanuel Macron", { kind: "entity", type: "person", name: "Emmanuel Macron" }],
    ["entity:org:Hamas", { kind: "entity", type: "org", name: "Hamas" }],
    ["entity:org:Unit: 8200", { kind: "entity", type: "org", name: "Unit: 8200" }],
    ["entity:org:" + "x".repeat(200), { kind: "entity", type: "org", name: "x".repeat(200) }],
  ])("parses %s", (raw, parsed) => {
    expect(parseItem(raw)).toEqual(parsed);
  });

  it.each([
    "",
    "article:",
    `article:${UUID.toUpperCase()}`,
    `article:${UUID.replaceAll("-", "")}`,
    `article:${UUID}x`,
    `article:${UUID}\n`,
    "place:48",
    "place:48.5:2",
    "place:048:2",
    "place:-0:2",
    "place:+48:2",
    "place:91:0",
    "place:0:181",
    "place:-91:0",
    "place:0:-181",
    "link:US-FR",
    "link:FR-FR",
    "link:fr-us",
    "link:FRA-USA",
    "thread:0",
    "thread:07",
    "thread:-7",
    "thread:9223372036854775808",
    "thread:abc",
    "entity:place:Paris",
    "entity:person:",
    "entity:person: Emmanuel Macron",
    "entity:person:Emmanuel  Macron",
    "entity:person:Emmanuel Macron\n",
    "entity:person:Emmanuel​Macron",
    "entity:person:Emmanuel\x01Macron",
    "entity:person:" + "x".repeat(201),
    "PLACE:48:2",
  ])("rejects %j", (raw) => {
    expect(parseItem(raw)).toBeNull();
  });

  it("rejects what isn't a string", () => {
    expect(parseItem(42)).toBeNull();
    expect(parseItem(null)).toBeNull();
    expect(parseItem({ item: "place:1:2" })).toBeNull();
  });

  it("builds an article's id from its uuid, lowercased; anything else has none", () => {
    expect(articleItem(UUID)).toBe(`article:${UUID}`);
    expect(articleItem(UUID.toUpperCase())).toBe(`article:${UUID}`);
    expect(articleItem("art-001")).toBeNull();
  });

  it("builds a place's id from its cell's floors: no -0, in range", () => {
    expect(placeItem(48.8566, 2.3522)).toBe("place:48:2");
    expect(placeItem(-33.87, 151.21)).toBe("place:-34:151");
    expect(placeItem(51.5, -0.13)).toBe("place:51:-1");
    expect(placeItem(0.5, -0)).toBe("place:0:0");
    expect(placeItem(-0.2, 0.4)).toBe("place:-1:0");
    expect(placeItem(90, 180)).toBe("place:90:180");
    expect(placeItem(91, 0)).toBeNull();
    expect(placeItem(Number.NaN, 0)).toBeNull();
  });

  it("builds a link's id in code order, from either end", () => {
    expect(linkItem("FR", "US")).toBe("link:FR-US");
    expect(linkItem("us", "fr")).toBe("link:FR-US");
    expect(linkItem("FR", "FR")).toBeNull();
    expect(linkItem("FRA", "US")).toBeNull();
  });

  it("builds a thread's id from a positive whole number", () => {
    expect(threadItem(7)).toBe("thread:7");
    expect(threadItem(0)).toBeNull();
    expect(threadItem(-3)).toBeNull();
    expect(threadItem(1.5)).toBeNull();
  });

  it("builds an entity's id from its name, trimmed and single-spaced, invisibles gone", () => {
    expect(entityItem("person", "Emmanuel Macron")).toBe("entity:person:Emmanuel Macron");
    expect(entityItem("org", "  Suez ​Canal  Authority ")).toBe("entity:org:Suez Canal Authority");
    expect(entityItem("org", "Bad\x01Name")).toBeNull();
    expect(entityItem("org", "   ")).toBeNull();
    expect(entityItem("org", "x".repeat(201))).toBeNull();
    // Every id built parses back as itself.
    expect(parseItem(entityItem("org", " A B ")!)).toEqual({
      kind: "entity",
      type: "org",
      name: "A B",
    });
    expect(canonicalName("‮A  B⁦")).toBe("A B");
  });

  it("names each kind", () => {
    expect(pinKindLabel(`article:${UUID}`)).toBe("Story");
    expect(pinKindLabel("place:48:2")).toBe("Place");
    expect(pinKindLabel("link:FR-US")).toBe("Link");
    expect(pinKindLabel("thread:7")).toBe("Thread");
    expect(pinKindLabel("entity:person:A")).toBe("Person");
    expect(pinKindLabel("entity:org:A")).toBe("Organisation");
  });

  it("gives an expired pin with nothing saved a title from its id", () => {
    expect(fallbackSnapshot("entity:org:Hamas").title).toBe("Hamas");
    expect(fallbackSnapshot("link:FR-US").title).toBe("FR and US");
    expect(fallbackSnapshot("place:48:2").title).toBe("48.5°, 2.5°");
    expect(fallbackSnapshot("place:48:2")).toMatchObject({ lat: 48.5, lng: 2.5 });
    expect(fallbackSnapshot("thread:7").title).toBe("Thread 7 (no longer available)");
    expect(fallbackSnapshot(`article:${UUID}`).title).toBe("A story no longer available");
  });
});

describe("snapshots", () => {
  it("keeps a snapshot's fields as their types allow", () => {
    expect(
      toSnapshot({
        title: "  France announces a policy ",
        place: "Paris, France",
        lat: 48.85,
        lng: 2.35,
        time: "2026-10-20T11:00:00Z",
        url: "https://example.com/a",
        resolved_as: "thread:9",
      }),
    ).toEqual({
      title: "France announces a policy",
      place: "Paris, France",
      lat: 48.85,
      lng: 2.35,
      time: "2026-10-20T11:00:00Z",
      url: "https://example.com/a",
    });
  });

  it("drops what isn't safe or well formed", () => {
    expect(
      toSnapshot({
        title: "A‮title",
        place: 5,
        lat: 120,
        lng: "x",
        time: "yesterday",
        url: "javascript:alert(1)",
      }),
    ).toEqual(snap("Atitle"));
    expect(toSnapshot({ title: "" })).toBeNull();
    expect(toSnapshot({ title: 3 })).toBeNull();
    expect(toSnapshot(null)).toBeNull();
    // Both coordinates or neither.
    expect(toSnapshot({ title: "T", lat: 10 })).toMatchObject({ lat: null, lng: null });
  });

  it("caps the title and place at what /api/board/analyze accepts", () => {
    const s = toSnapshot({ title: "t".repeat(900), place: "p".repeat(400) })!;
    expect(s.title).toHaveLength(500);
    expect(s.place).toHaveLength(200);
  });
});

describe("the board's state", () => {
  it("adds a pin at the first free slot, with its time", () => {
    const one = addPin(board(), "place:48:2", snap("Paris"), 1000);
    expect(one.pins).toEqual([
      { item: "place:48:2", snapshot: snap("Paris"), ...nextSlot([]), pinnedAt: 1000 },
    ]);
    const two = addPin(one, "thread:7", snap("Red Sea"), 2000);
    expect(two.pins[1]).toMatchObject({ item: "thread:7", ...nextSlot(one.pins) });
    expect(nextSlot(one.pins)).not.toEqual(nextSlot([]));
  });

  it("ignores a pin already in, an id that isn't one, and a 21st", () => {
    const one = addPin(board(), "place:48:2", snap("Paris"), 1);
    expect(addPin(one, "place:48:2", snap("Again"), 2)).toBe(one);
    expect(addPin(one, "place:48.5:2", snap("Bad"), 2)).toBe(one);
    let full = board();
    for (let i = 1; i <= MAX_PINS; i++) full = addPin(full, `thread:${i}`, snap(`T${i}`), i);
    expect(full.pins).toHaveLength(MAX_PINS);
    expect(addPin(full, "thread:99", snap("One more"), 99)).toBe(full);
  });

  it("removes and moves pins, keeping positions on the board", () => {
    const b = board(pin("thread:1"), pin("thread:2"));
    expect(removePin(b, "thread:1").pins.map((p) => p.item)).toEqual(["thread:2"]);
    expect(movePin(b, "thread:2", 0.2, 0.9).pins[1]).toMatchObject({ x: 0.2, y: 0.9 });
    expect(movePin(b, "thread:2", -1, 4).pins[1]).toMatchObject({ x: 0, y: 1 });
    expect(movePin(b, "thread:9", 0.1, 0.1)).toBe(b);
  });

  it("fills the slots without stacking cards, then wraps", () => {
    let b = board();
    for (let i = 1; i <= MAX_PINS; i++) b = addPin(b, `thread:${i}`, snap(`T${i}`), i);
    const spots = new Set(b.pins.map((p) => `${p.x.toFixed(3)},${p.y.toFixed(3)}`));
    expect(spots.size).toBe(MAX_PINS);
    for (const p of b.pins) {
      expect(p.x).toBeGreaterThanOrEqual(0);
      expect(p.x).toBeLessThanOrEqual(1);
      expect(p.y).toBeGreaterThanOrEqual(0);
      expect(p.y).toBeLessThanOrEqual(1);
    }
  });
});

describe("moving a card with the keyboard", () => {
  it("steps with the arrow keys, further with Shift, within the board", () => {
    expect(keyMove({ x: 0.5, y: 0.5 }, "ArrowRight", false)).toEqual({ x: 0.52, y: 0.5 });
    expect(keyMove({ x: 0.5, y: 0.5 }, "ArrowLeft", true)).toEqual({ x: 0.4, y: 0.5 });
    expect(keyMove({ x: 0.5, y: 0.5 }, "ArrowUp", false)).toEqual({ x: 0.5, y: 0.48 });
    expect(keyMove({ x: 0.5, y: 0.95 }, "ArrowDown", true)).toEqual({ x: 0.5, y: 1 });
    expect(keyMove({ x: 0.01, y: 0.5 }, "ArrowLeft", false)).toEqual({ x: 0, y: 0.5 });
    expect(keyMove({ x: 0.5, y: 0.5 }, "Enter", false)).toBeNull();
  });

  it("says where a card is, for screen readers", () => {
    expect(positionWords({ x: 0.404, y: 0.25 })).toBe("40% across, 25% down");
  });
});

describe("storage", () => {
  const stored = (value: unknown) => ({ getItem: () => JSON.stringify(value) });

  it("reads the stored board, keeping well-formed pins", () => {
    const pins = [pin("place:48:2"), pin("thread:7", { x: 0.1, y: 0.2 })];
    expect(readBoard(stored({ pins }))).toEqual({ pins });
  });

  it("is empty for nothing stored, corrupt JSON, or storage that throws", () => {
    expect(readBoard({ getItem: () => null })).toEqual({ pins: [] });
    expect(readBoard({ getItem: () => "{not json" })).toEqual({ pins: [] });
    expect(readBoard({ getItem: () => "[1,2]" })).toEqual({ pins: [] });
    expect(
      readBoard({
        getItem: () => {
          throw new DOMException("blocked", "SecurityError");
        },
      }),
    ).toEqual({ pins: [] });
    expect(readBoard(null)).toEqual({ pins: [] });
  });

  it("drops malformed and repeated pins, clamps positions, and keeps at most 20", () => {
    const many = Array.from({ length: 25 }, (_, i) => pin(`thread:${i + 1}`));
    expect(readBoard(stored({ pins: many })).pins).toHaveLength(MAX_PINS);
    const read = boardFromJson(
      JSON.stringify({
        pins: [
          pin("place:48:2", { x: 7, y: -2 }),
          pin("place:48:2"),
          { ...pin("thread:1"), item: "thread:01" },
          { ...pin("thread:2"), snapshot: { title: "" } },
          { ...pin("thread:3"), x: "left" },
          "garbage",
        ],
      }),
    );
    expect(read.pins.map((p) => [p.item, p.x, p.y])).toEqual([["place:48:2", 1, 0]]);
  });

  it("writes the board under its key, and says false when storage refuses", () => {
    const setItem = vi.fn();
    const state = board(pin("place:48:2"));
    expect(writeBoard(state, { setItem })).toBe(true);
    expect(setItem).toHaveBeenCalledWith(BOARD_KEY, JSON.stringify(state));
    expect(
      writeBoard(state, {
        setItem: () => {
          throw new DOMException("full", "QuotaExceededError");
        },
      }),
    ).toBe(false);
    expect(writeBoard(state, null)).toBe(false);
  });
});

describe("refreshing pins from /api/board/resolve", () => {
  it("takes the server's snapshot, and keeps the stored one for an expired pin", () => {
    const b = board(pin("place:48:2"), pin("thread:7"));
    const next = applyResolved(b, [
      { item: "place:48:2", snapshot: { title: "Paris, France", lat: 48.5, lng: 2.5 } },
      { item: "thread:7", snapshot: null },
    ]);
    expect(next.pins[0].snapshot).toMatchObject({ title: "Paris, France", lat: 48.5 });
    expect(next.pins[1].snapshot).toEqual(b.pins[1].snapshot);
  });

  it("swaps a merged thread's pin to the thread it joined, or drops it when that is pinned", () => {
    const b = board(pin("thread:7", { x: 0.3 }), pin("thread:8"), pin("thread:9"));
    const next = applyResolved(b, [
      { item: "thread:7", snapshot: { title: "Red Sea", resolved_as: "thread:12" } },
      { item: "thread:8", snapshot: { title: "Same as 9", resolved_as: "thread:9" } },
      { item: "thread:9", snapshot: { title: "Nine", resolved_as: null } },
    ]);
    expect(next.pins.map((p) => p.item)).toEqual(["thread:12", "thread:9"]);
    expect(next.pins[0]).toMatchObject({ x: 0.3, snapshot: { title: "Red Sea" } });
  });

  it("ignores a malformed resolved_as and answers for pins it doesn't hold", () => {
    const b = board(pin("thread:7"));
    const next = applyResolved(b, [
      { item: "thread:7", snapshot: { title: "Seven", resolved_as: "thread:07" } },
      { item: "thread:99", snapshot: { title: "Not pinned" } },
    ]);
    expect(next.pins.map((p) => [p.item, p.snapshot.title])).toEqual([["thread:7", "Seven"]]);
  });
});

describe("merging shared pins", () => {
  const shared = (item: string) => ({ item, snapshot: snap(item) });

  it("adds the shared pins the board lacks, as far as there is room", () => {
    const b = board(pin("thread:1"));
    const { state, added, skipped } = mergePins(
      b,
      [shared("thread:1"), shared("thread:2"), shared("place:48:2")],
      5,
    );
    expect(state.pins.map((p) => p.item)).toEqual(["thread:1", "thread:2", "place:48:2"]);
    expect([added, skipped]).toEqual([2, 0]);
  });

  it("stops at 20 pins and says how many didn't fit", () => {
    let b = board();
    for (let i = 1; i <= 19; i++) b = addPin(b, `thread:${i}`, snap(`T${i}`), i);
    const entries = [shared("place:1:1"), shared("place:2:2"), shared("place:3:3")];
    expect(mergePlan(b, entries)).toEqual({ fresh: 3, fit: 1 });
    const { state, added, skipped } = mergePins(b, entries, 5);
    expect(state.pins).toHaveLength(MAX_PINS);
    expect([added, skipped]).toEqual([1, 2]);
  });
});

describe("a share link's pins, resolved", () => {
  it("takes each one's snapshot, or a stand-in from its id; drops the refused", () => {
    const entries = sharedEntries(
      ["thread:7", "entity:org:Hamas", "link:FR-ZZ", "place:48:2"],
      [
        { item: "thread:7", snapshot: { title: "Red Sea", resolved_as: "thread:9" } },
        { item: "entity:org:Hamas", snapshot: null },
        { item: "place:48:2", snapshot: { title: "Paris, France", lat: 48.5, lng: 2.5 } },
      ],
      ["link:FR-ZZ"],
    );
    expect(entries.map((e) => [e.item, e.snapshot.title])).toEqual([
      ["thread:9", "Red Sea"],
      ["entity:org:Hamas", "Hamas"],
      ["place:48:2", "Paris, France"],
    ]);
  });

  it("keeps one pin for two that are now the same thread", () => {
    const entries = sharedEntries(
      ["thread:7", "thread:9"],
      [
        { item: "thread:7", snapshot: { title: "Red Sea", resolved_as: "thread:9" } },
        { item: "thread:9", snapshot: { title: "Red Sea" } },
      ],
      [],
    );
    expect(entries.map((e) => e.item)).toEqual(["thread:9"]);
  });
});

describe("share links", () => {
  const ids = [
    `article:${UUID}`,
    "place:-34:151",
    "link:FR-US",
    "thread:7",
    "entity:person:Élisabeth Borne",
    "entity:org:Unit: 8200",
  ];

  it("round-trips up to 20 ids through base64url", () => {
    const encoded = encodeShare(ids);
    expect(encoded).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(decodeShare(encoded)).toEqual(ids);
  });

  it("builds the link on the page's own address, with nothing else in it", () => {
    const url = shareUrl("https://orbisapp.co/?x=1#top", ids.slice(0, 2));
    expect(url).toBe(`https://orbisapp.co/?board=${encodeShare(ids.slice(0, 2))}`);
  });

  it("drops invalid and repeated ids, and keeps at most 20", () => {
    const many = Array.from({ length: 30 }, (_, i) => `thread:${i + 1}`);
    expect(decodeShare(encodeShare(many))).toEqual(many.slice(0, MAX_PINS));
    const mixed = encodeShare(["thread:7", "thread:07", "javascript:alert(1)", "thread:7", OTHER]);
    expect(decodeShare(mixed)).toEqual(["thread:7"]);
  });

  it("decodes nothing from garbage, padding or a link too long", () => {
    expect(decodeShare(null)).toEqual([]);
    expect(decodeShare("")).toEqual([]);
    expect(decodeShare("not base64!")).toEqual([]);
    expect(decodeShare(encodeShare(["thread:7"]) + "=")).toEqual([]);
    expect(decodeShare("A".repeat(SHARE_MAX_CHARS + 1))).toEqual([]);
    // Bytes that aren't UTF-8.
    expect(decodeShare("_w")).toEqual([]);
  });
});
