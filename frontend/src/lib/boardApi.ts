/**
 * The board's requests (backend routers/board.py): what pins are now
 * (/resolve), the typed edges between them (/links) and a cited AI memo on
 * them (/analyze). The board itself never leaves the browser otherwise.
 */
import { ApiError } from "@/lib/api";
import { cleanLabel } from "@/hooks/useAgent";
import { MAX_PINS, parseItem, type Pin, type ResolvedItem } from "@/lib/board";
import { toBoardLinks, type BoardEdge } from "@/lib/boardEdges";

/** The memo's three sections, in order (backend MemoSection). */
export const MEMO_HEADINGS = ["Possible connections", "Contradictions", "Open questions"] as const;

/** The server's own words for a board with too little on it (asked for nothing here). */
export const MEMO_TOO_FEW = "Not enough on the board to analyse: pin at least two items.";
/** The `ai` rate limit (10 a minute) answered 429. */
export const MEMO_RATE_LIMITED = "Too many analyses in the last minute. Try again shortly.";
export const MEMO_FAILED = "Couldn't analyse the board right now. Try again in a moment.";

export interface MemoSection {
  heading: string;
  /** Plain sentences citing pins as [n]. */
  text: string;
}

/** An analysis: the memo, or a message saying why there is none. */
export interface BoardMemo {
  sections: MemoSection[];
  /** Each pin cited, by its number in `items`. */
  citations: { n: number; item: string }[];
  message: string | null;
  /** The pins asked about, in order: [n] is the n-th. */
  items: string[];
}

/** POST JSON to a same-origin /api route (the proxy adds the API key). */
function post(path: string, body: unknown, signal?: AbortSignal): Promise<Response> {
  return fetch(new URL(path, window.location.origin).toString(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    ...(signal ? { signal } : {}),
  });
}

/** The index a 422 names ("items[3] is not a board item id."), or null. */
async function refusedIndex(res: Response): Promise<number | null> {
  try {
    const detail = ((await res.json()) as { detail?: unknown })?.detail;
    const m = typeof detail === "string" ? /^items\[(\d+)\]/.exec(detail) : null;
    return m ? Number(m[1]) : null;
  } catch {
    return null;
  }
}

/**
 * What each pin is now, in board order: a snapshot, or null when the server
 * no longer knows it. An id the server refuses (a link to a country without a
 * label point, say: the board can't check that) is dropped and the rest asked
 * again; `rejected` lists those.
 */
export async function resolveItems(
  items: readonly string[],
  signal?: AbortSignal,
): Promise<{ items: ResolvedItem[]; rejected: string[] }> {
  let asked = [...items];
  const rejected: string[] = [];
  while (asked.length > 0) {
    const res = await post("/api/board/resolve", { items: asked }, signal);
    if (res.ok) {
      const data = (await res.json()) as { items?: unknown };
      const list = Array.isArray(data?.items) ? data.items : [];
      const resolved = list
        .map((r) => r as { item?: unknown; snapshot?: unknown })
        .filter((r): r is ResolvedItem => typeof r?.item === "string")
        .map((r) => ({ item: r.item, snapshot: r.snapshot ?? null }));
      return { items: resolved, rejected };
    }
    const index = res.status === 422 ? await refusedIndex(res) : null;
    if (index === null || index >= asked.length) throw new ApiError(res.status, res.statusText);
    rejected.push(asked[index]);
    asked = asked.filter((_, i) => i !== index);
  }
  return { items: [], rejected };
}

/** The typed edges between the pins (board order: each runs from the earlier pin). */
export async function fetchBoardLinks(
  items: readonly string[],
  signal?: AbortSignal,
): Promise<{ edges: BoardEdge[]; coCoverageChecked: boolean }> {
  const res = await post("/api/board/links", { items }, signal);
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  return toBoardLinks(await res.json());
}

/** What /api/board/analyze is sent: each pin with its saved title, place and time. */
export function analyzeBody(pins: readonly Pin[]) {
  return {
    items: pins.map((p) => {
      const t = p.snapshot.time ? Date.parse(p.snapshot.time) : NaN;
      return {
        item: p.item,
        snapshot: {
          title: p.snapshot.title,
          place: p.snapshot.place,
          time: Number.isFinite(t) ? new Date(t).toISOString() : null,
        },
      };
    }),
  };
}

const noMemo = (items: string[], message: string): BoardMemo => ({
  sections: [],
  citations: [],
  message,
  items,
});

/** The memo, cleaned: the known sections with text, citations of pins asked about. */
function toMemo(raw: unknown, items: string[]): BoardMemo {
  const r = (raw ?? {}) as { sections?: unknown; citations?: unknown; message?: unknown };
  const message = typeof r.message === "string" ? cleanLabel(r.message, 500) : "";
  if (message) return noMemo(items, message);
  const sections: MemoSection[] = [];
  for (const s of Array.isArray(r.sections) ? r.sections : []) {
    const { heading, text } = (s ?? {}) as Record<string, unknown>;
    const words = cleanLabel(text, 4000);
    if (MEMO_HEADINGS.includes(heading as (typeof MEMO_HEADINGS)[number]) && words) {
      sections.push({ heading: heading as string, text: words });
    }
  }
  if (sections.length === 0) return noMemo(items, MEMO_FAILED);
  const citations: BoardMemo["citations"] = [];
  for (const c of Array.isArray(r.citations) ? r.citations : []) {
    const { n, item } = (c ?? {}) as Record<string, unknown>;
    if (typeof n !== "number" || !Number.isInteger(n) || n < 1 || n > items.length) continue;
    if (!parseItem(item) || citations.some((x) => x.n === n)) continue;
    citations.push({ n, item: item as string });
  }
  return { sections, citations, message: null, items };
}

/**
 * Claude's memo on the pins: possible connections, contradictions and open
 * questions, citing pins as [n]. Fewer than two pins ask nothing. A failure
 * or the rate limit (429) is a message, said kindly; an abort is thrown.
 */
export async function analyzePins(pins: readonly Pin[], signal?: AbortSignal): Promise<BoardMemo> {
  const items = pins.slice(0, MAX_PINS).map((p) => p.item);
  if (items.length < 2) return noMemo(items, MEMO_TOO_FEW);
  let res: Response;
  try {
    res = await post("/api/board/analyze", analyzeBody(pins.slice(0, MAX_PINS)), signal);
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    return noMemo(items, MEMO_FAILED);
  }
  if (res.status === 429) return noMemo(items, MEMO_RATE_LIMITED);
  if (!res.ok) return noMemo(items, MEMO_FAILED);
  try {
    return toMemo(await res.json(), items);
  } catch {
    return noMemo(items, MEMO_FAILED);
  }
}

/** A memo's text in pieces: words, and the [n] that cite pins. */
export function memoParts(text: string): ({ text: string } | { n: number })[] {
  const parts: ({ text: string } | { n: number })[] = [];
  const re = /\[(\d{1,2})\]/g;
  let last = 0;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    if (m.index > last) parts.push({ text: text.slice(last, m.index) });
    parts.push({ n: Number(m[1]) });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last) });
  return parts;
}
