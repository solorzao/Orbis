/**
 * The investigation board: pins kept in this browser (localStorage), each an
 * item id the server knows (backend services/board.py) and a snapshot of what
 * it was, so a pin outlives the stories' 7-day retention. Ids are built and
 * read here exactly as the backend parses them (a malformed one is a 422 for
 * the whole request), and travel in share links as base64url.
 */
import { cleanLabel, isWebUrl } from "@/hooks/useAgent";
import type { EntityType } from "@/lib/entities";

/** localStorage: the board, `{pins: [{item, snapshot, x, y, pinnedAt}]}`. */
export const BOARD_KEY = "orbis-board-v1";
/** Pins a board holds (and so the most a request names: backend MAX_ITEMS). */
export const MAX_PINS = 20;
/** An entity name's characters, at most (backend MAX_NAME). */
export const MAX_NAME = 200;
/** What /api/board/analyze accepts of a saved snapshot. */
export const MAX_TITLE = 500;
export const MAX_PLACE = 200;
const MAX_URL = 2048;
/** The share link's query parameter: `?board=<base64url of the ids>`. */
export const SHARE_PARAM = "board";
/** The longest share parameter: 20 ids of a 200-character name in 4-byte characters. */
export const SHARE_MAX_CHARS =
  Math.ceil((MAX_PINS * ("entity:person:".length + MAX_NAME * 4) + MAX_PINS - 1) / 3) * 4;

export type PinKind = "article" | "place" | "link" | "thread" | "entity";

/** An item id, read: what it names. */
export type ParsedItem =
  | { kind: "article"; id: string }
  | { kind: "place"; lat: number; lng: number }
  | { kind: "link"; a: string; b: string }
  /** The id as written: it may exceed what a JS number holds exactly. */
  | { kind: "thread"; id: string }
  | { kind: "entity"; type: EntityType; name: string };

/** What a pin is, as the server last said (or as it was pinned): enough to show it once expired. */
export interface PinSnapshot {
  /** A headline, a place, "A and B", a thread's title or a name. */
  title: string;
  place: string | null;
  lat: number | null;
  lng: number | null;
  /** ISO: a story's time, a place's newest, a thread's last; none for links and names. */
  time: string | null;
  /** A story's http(s) link. */
  url: string | null;
}

export interface Pin {
  item: string;
  snapshot: PinSnapshot;
  /** Where its card sits on the board: 0 to 1 across and down the room for it. */
  x: number;
  y: number;
  /** When it was pinned (ms). */
  pinnedAt: number;
}

export interface BoardState {
  pins: Pin[];
}

export const EMPTY_BOARD: BoardState = { pins: [] };

// ── Item ids ────────────────────────────────────────────────────────

const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const DEGREE = "0|-?[1-9][0-9]{0,2}";
const ARTICLE = new RegExp(`^article:(${UUID})$`);
const PLACE = new RegExp(`^place:(${DEGREE}):(${DEGREE})$`);
const LINK = /^link:([A-Z]{2})-([A-Z]{2})$/;
const THREAD = /^thread:([1-9][0-9]{0,18})$/;
const ENTITY = /^entity:(person|org):([\s\S]+)$/;
const MAX_BIGINT = BigInt("9223372036854775807");
const CONTROL = /[\x00-\x1f\x7f]/;
// What the backend's strip_invisible removes (security._INVISIBLE): C1 controls,
// the Arabic letter mark, zero-width and bidi marks, joiners, isolates, the BOM, tags.
const INVISIBLE = /[\x80-\x9f؜​-‏‪-‮⁠-⁩﻿\u{e0000}-\u{e007f}]/gu;

/** A name as the backend normalises one: invisible characters gone, trimmed and single-spaced. */
export function canonicalName(name: string): string {
  return name.replace(INVISIBLE, "").split(/\s+/u).filter(Boolean).join(" ");
}

/** `raw` read as a board item id, exactly as the backend's parse_item reads one, or null. */
export function parseItem(raw: unknown): ParsedItem | null {
  if (typeof raw !== "string") return null;
  let m = ARTICLE.exec(raw);
  if (m) return { kind: "article", id: m[1] };
  m = PLACE.exec(raw);
  if (m) {
    const lat = Number(m[1]);
    const lng = Number(m[2]);
    return Math.abs(lat) <= 90 && Math.abs(lng) <= 180 ? { kind: "place", lat, lng } : null;
  }
  m = LINK.exec(raw);
  if (m) return m[1] < m[2] ? { kind: "link", a: m[1], b: m[2] } : null;
  m = THREAD.exec(raw);
  if (m) return BigInt(m[1]) <= MAX_BIGINT ? { kind: "thread", id: m[1] } : null;
  m = ENTITY.exec(raw);
  if (m) {
    const name = m[2];
    const ok =
      Array.from(name).length <= MAX_NAME && name === canonicalName(name) && !CONTROL.test(name);
    return ok ? { kind: "entity", type: m[1] as EntityType, name } : null;
  }
  return null;
}

const valid = (id: string) => (parseItem(id) ? id : null);

/** A story's pin id from its uuid (lowercased, as the API gives ids), or null for any other id. */
export function articleItem(id: string): string | null {
  return valid(`article:${id.toLowerCase()}`);
}

/** A place's pin id: its 1° cell's floors (the globe's grid), never "-0". */
export function placeItem(lat: number, lng: number): string | null {
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  const floor = (v: number) => Math.floor(v) + 0; // + 0 turns -0 into 0
  return valid(`place:${floor(lat)}:${floor(lng)}`);
}

/** Two countries covered together: their codes in code order, as /api/links gives pairs. */
export function linkItem(a: string, b: string): string | null {
  const [x, y] = [a.toUpperCase(), b.toUpperCase()].sort();
  return valid(`link:${x}-${y}`);
}

export function threadItem(id: number): string | null {
  return Number.isSafeInteger(id) && id > 0 ? valid(`thread:${id}`) : null;
}

/** A person's or organisation's pin id, by the dossier's name (normalised as the server does). */
export function entityItem(type: EntityType, name: string): string | null {
  return valid(`entity:${type}:${canonicalName(name)}`);
}

/** What a pin is, in a word: Story, Place, Link, Thread, Person or Organisation. */
export function pinKindLabel(item: string): string {
  const parsed = parseItem(item);
  switch (parsed?.kind) {
    case "article":
      return "Story";
    case "place":
      return "Place";
    case "link":
      return "Link";
    case "thread":
      return "Thread";
    case "entity":
      return parsed.type === "person" ? "Person" : "Organisation";
    default:
      return "Pin";
  }
}

// ── Snapshots ───────────────────────────────────────────────────────

const coordinate = (v: unknown, limit: number) =>
  typeof v === "number" && Number.isFinite(v) && Math.abs(v) <= limit ? v : null;

const text = (v: unknown, max: number) => {
  const s = typeof v === "string" ? cleanLabel(v, max) : "";
  return s === "" ? null : s;
};

/**
 * A snapshot from the server or from storage, each field as its type allows:
 * text cleaned of invisible and control characters and capped at what
 * /api/board/analyze accepts, both coordinates or neither, a parseable time,
 * an http(s) link only. Null without a title.
 */
export function toSnapshot(raw: unknown): PinSnapshot | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const title = text(r.title, MAX_TITLE);
  if (title === null) return null;
  const lat = coordinate(r.lat, 90);
  const lng = coordinate(r.lng, 180);
  const both = lat !== null && lng !== null;
  const time = typeof r.time === "string" && Number.isFinite(Date.parse(r.time)) ? r.time : null;
  const url =
    isWebUrl(r.url) && r.url.length <= MAX_URL && !/[\s\x00-\x1f\x7f<>"]/.test(r.url)
      ? r.url
      : null;
  return {
    title,
    place: text(r.place, MAX_PLACE),
    lat: both ? lat : null,
    lng: both ? lng : null,
    time,
    url,
  };
}

/** A shared pin the server no longer knows, with nothing saved: what its id says. */
export function fallbackSnapshot(item: string): PinSnapshot {
  const parsed = parseItem(item);
  const none = { place: null, lat: null, lng: null, time: null, url: null };
  switch (parsed?.kind) {
    case "entity":
      return { ...none, title: parsed.name };
    case "link":
      return { ...none, title: `${parsed.a} and ${parsed.b}` };
    case "place": {
      const lat = Math.min(parsed.lat + 0.5, 90);
      const lng = Math.min(parsed.lng + 0.5, 180);
      return { ...none, title: `${lat}°, ${lng}°`, lat, lng };
    }
    case "thread":
      return { ...none, title: `Thread ${parsed.id} (no longer available)` };
    default:
      return { ...none, title: "A story no longer available" };
  }
}

// ── Where cards go ──────────────────────────────────────────────────

const round = (v: number) => Math.round(v * 1e4) / 1e4;
const clamp01 = (v: number) => round(Math.min(1, Math.max(0, v)));

/**
 * The board's default spots, in the order pins take them: around an outer
 * ellipse, spread out (top, bottom, right, left, then between), then an inner
 * one. Edges between cards then cross the open middle.
 */
const SLOTS: { x: number; y: number }[] = (() => {
  const ring = (n: number, r: number, order: number[]) =>
    order.map((k) => {
      const a = ((-90 + (k * 360) / n) * Math.PI) / 180;
      return { x: round(0.5 + r * Math.cos(a)), y: round(0.5 + r * Math.sin(a)) };
    });
  return [
    ...ring(12, 0.5, [0, 6, 3, 9, 2, 8, 5, 11, 1, 7, 4, 10]),
    ...ring(8, 0.22, [0, 4, 2, 6, 1, 5, 3, 7]),
  ];
})();
/** A spot is taken when a card sits this close to it, across and down. */
const NEAR = 0.06;

/** Where a new pin's card goes: the first default spot no card sits on. */
export function nextSlot(pins: readonly Pin[]): { x: number; y: number } {
  const free = SLOTS.find(
    (s) => !pins.some((p) => Math.abs(p.x - s.x) < NEAR && Math.abs(p.y - s.y) < NEAR),
  );
  return free ?? SLOTS[pins.length % SLOTS.length];
}

/** An arrow key's step across the board; Shift moves five times as far. */
export const KEY_STEP = 0.02;
const BIG_STEP = 0.1;

/** Where an arrow key moves a card, kept on the board; null for any other key. */
export function keyMove(
  pos: { x: number; y: number },
  key: string,
  big: boolean,
): { x: number; y: number } | null {
  const step = big ? BIG_STEP : KEY_STEP;
  const delta: Record<string, [number, number]> = {
    ArrowLeft: [-step, 0],
    ArrowRight: [step, 0],
    ArrowUp: [0, -step],
    ArrowDown: [0, step],
  };
  const d = delta[key];
  return d ? { x: clamp01(pos.x + d[0]), y: clamp01(pos.y + d[1]) } : null;
}

/** Where a card is, in words: "40% across, 25% down". */
export function positionWords({ x, y }: { x: number; y: number }): string {
  return `${Math.round(x * 100)}% across, ${Math.round(y * 100)}% down`;
}

// ── The board's state ───────────────────────────────────────────────

/** The board with `item` pinned (at the first free spot), or as it was: already in, malformed or full. */
export function addPin(
  state: BoardState,
  item: string,
  snapshot: PinSnapshot,
  now: number,
): BoardState {
  if (!parseItem(item) || state.pins.length >= MAX_PINS) return state;
  if (state.pins.some((p) => p.item === item)) return state;
  return { pins: [...state.pins, { item, snapshot, ...nextSlot(state.pins), pinnedAt: now }] };
}

export function removePin(state: BoardState, item: string): BoardState {
  return { pins: state.pins.filter((p) => p.item !== item) };
}

/** The board with `item`'s card moved (kept on the board), or as it was when it isn't pinned. */
export function movePin(state: BoardState, item: string, x: number, y: number): BoardState {
  if (!state.pins.some((p) => p.item === item)) return state;
  return {
    pins: state.pins.map((p) => (p.item === item ? { ...p, x: clamp01(x), y: clamp01(y) } : p)),
  };
}

/** One stored pin, if it is well formed: a valid id, a snapshot with a title, a position. */
function readPin(raw: unknown): Pin | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const snapshot = toSnapshot(r.snapshot);
  if (!parseItem(r.item) || !snapshot) return null;
  if (typeof r.x !== "number" || typeof r.y !== "number") return null;
  if (!Number.isFinite(r.x) || !Number.isFinite(r.y)) return null;
  const pinnedAt = typeof r.pinnedAt === "number" && Number.isFinite(r.pinnedAt) ? r.pinnedAt : 0;
  return { item: r.item as string, snapshot, x: clamp01(r.x), y: clamp01(r.y), pinnedAt };
}

/** The board stored as JSON: well-formed pins once each, at most 20; empty for anything else. */
export function boardFromJson(raw: string | null): BoardState {
  if (!raw) return EMPTY_BOARD;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return EMPTY_BOARD; // corrupt: start again
  }
  const list = (parsed as { pins?: unknown } | null)?.pins;
  if (!Array.isArray(list)) return EMPTY_BOARD;
  const pins: Pin[] = [];
  for (const entry of list) {
    const pin = readPin(entry);
    if (!pin || pins.some((p) => p.item === pin.item)) continue;
    pins.push(pin);
    if (pins.length === MAX_PINS) break;
  }
  return { pins };
}

/** The stored board, or an empty one when there is none, it is corrupt or storage is blocked. */
export function readBoard(storage: Pick<Storage, "getItem"> | null | undefined): BoardState {
  try {
    return boardFromJson(storage?.getItem(BOARD_KEY) ?? null);
  } catch {
    return EMPTY_BOARD; // storage blocked: the board lives in memory
  }
}

/** Store the board; false when storage is blocked or full (the board stays in memory). */
export function writeBoard(
  state: BoardState,
  storage: Pick<Storage, "setItem"> | null | undefined,
): boolean {
  if (!storage) return false;
  try {
    storage.setItem(BOARD_KEY, JSON.stringify(state));
    return true;
  } catch {
    return false;
  }
}

/** One item of /api/board/resolve's answer: the snapshot, null when unknown or expired. */
export interface ResolvedItem {
  item: string;
  snapshot: unknown;
}

/** The thread a pinned thread merged into (a snapshot's `resolved_as`), when it is another valid one. */
function mergedInto(snapshot: unknown, item: string): string | null {
  const merged = (snapshot as { resolved_as?: unknown } | null | undefined)?.resolved_as;
  return typeof merged === "string" && merged !== item && parseItem(merged)?.kind === "thread"
    ? merged
    : null;
}

/**
 * A share link's pins, resolved: each with the server's snapshot, or a
 * stand-in from its id when the server no longer knows it; a merged thread
 * as the thread it joined (once); the ids the server refused left out.
 */
export function sharedEntries(
  ids: readonly string[],
  results: readonly ResolvedItem[],
  rejected: readonly string[],
): { item: string; snapshot: PinSnapshot }[] {
  const byItem = new Map(results.map((r) => [r.item, r.snapshot]));
  const entries: { item: string; snapshot: PinSnapshot }[] = [];
  for (const id of ids) {
    if (rejected.includes(id)) continue;
    const raw = byItem.get(id);
    const item = mergedInto(raw, id) ?? id;
    if (entries.some((e) => e.item === item)) continue;
    entries.push({ item, snapshot: toSnapshot(raw) ?? fallbackSnapshot(item) });
  }
  return entries;
}

/**
 * The pins refreshed from /api/board/resolve. A pin the server no longer
 * knows keeps its stored snapshot. A thread that merged into another
 * (`resolved_as`) takes that thread's id, as the Threads layer adopts it, or
 * goes when that thread is pinned already.
 */
export function applyResolved(state: BoardState, results: readonly ResolvedItem[]): BoardState {
  const byItem = new Map(results.map((r) => [r.item, r.snapshot]));
  const pinned = new Set(state.pins.map((p) => p.item));
  const seen = new Set<string>();
  const pins: Pin[] = [];
  for (const p of state.pins) {
    const raw = byItem.get(p.item);
    const snapshot = toSnapshot(raw) ?? p.snapshot;
    const swap = mergedInto(raw, p.item);
    const item = swap ?? p.item;
    if ((swap && pinned.has(item)) || seen.has(item)) continue;
    seen.add(item);
    pins.push({ ...p, item, snapshot });
  }
  return { pins };
}

/** Shared pins: the ones the board lacks, and how many of them fit. */
export function mergePlan(
  state: BoardState,
  entries: readonly { item: string }[],
): { fresh: number; fit: number } {
  const have = new Set(state.pins.map((p) => p.item));
  const fresh = new Set(entries.map((e) => e.item).filter((i) => parseItem(i) && !have.has(i)));
  return { fresh: fresh.size, fit: Math.min(fresh.size, MAX_PINS - state.pins.length) };
}

/** The board with the shared pins it lacks added, as far as there is room. */
export function mergePins(
  state: BoardState,
  entries: readonly { item: string; snapshot: PinSnapshot }[],
  now: number,
): { state: BoardState; added: number; skipped: number } {
  const { fresh } = mergePlan(state, entries);
  let next = state;
  for (const e of entries) next = addPin(next, e.item, e.snapshot, now);
  const added = next.pins.length - state.pins.length;
  return { state: next, added, skipped: fresh - added };
}

// ── Share links ─────────────────────────────────────────────────────

const BASE64URL = /^[A-Za-z0-9_-]+$/;

/** The ids, one per line (no id holds a line break), as UTF-8 in base64url without padding. */
export function encodeShare(items: readonly string[]): string {
  const bytes = new TextEncoder().encode(items.join("\n"));
  let binary = "";
  bytes.forEach((b) => (binary += String.fromCharCode(b)));
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/**
 * A share link's ids, read defensively (it is anyone's input): base64url of
 * UTF-8 within a size cap, each id valid as the server parses it, once each,
 * at most 20. Anything else is dropped; garbage gives none.
 */
export function decodeShare(param: string | null | undefined): string[] {
  if (typeof param !== "string" || param.length > SHARE_MAX_CHARS || !BASE64URL.test(param)) {
    return [];
  }
  let decoded: string;
  try {
    const b64 = param.replace(/-/g, "+").replace(/_/g, "/");
    const binary = atob(b64 + "=".repeat((4 - (b64.length % 4)) % 4));
    const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
    decoded = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return [];
  }
  const items: string[] = [];
  for (const id of decoded.split("\n")) {
    if (!parseItem(id) || items.includes(id)) continue;
    items.push(id);
    if (items.length === MAX_PINS) break;
  }
  return items;
}

/** The share link for these ids, on the page's own address (nothing else of it carried over). */
export function shareUrl(href: string, items: readonly string[]): string {
  const url = new URL(href);
  return `${url.origin}${url.pathname}?${SHARE_PARAM}=${encodeShare(items)}`;
}
