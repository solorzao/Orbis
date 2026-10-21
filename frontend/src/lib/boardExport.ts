/**
 * The board as Markdown (Export): its pins with their snapshots and web
 * links, the edges between them by pin number, and the AI memo if there is
 * one. Every text from data is escaped, so a title can't become a link,
 * heading or HTML in whatever renders the file.
 */
import { isWebUrl } from "@/hooks/useAgent";
import { pinKindLabel, type Pin } from "@/lib/board";
import type { BoardEdge } from "@/lib/boardEdges";
import type { BoardMemo } from "@/lib/boardApi";

export const EXPORT_FILENAME = "orbis-board.md";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "20 Oct 2026, 11:00 UTC". */
function utcStamp(ms: number): string {
  const d = new Date(ms);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}, ${hh}:${mm} UTC`;
}

/** Text from data as one line of Markdown that reads as itself: every syntax character escaped. */
export function escapeMarkdown(text: string): string {
  return text
    .replace(/\s+/g, " ")
    .trim()
    .replace(/[\\`*_{}[\]()#+\-.!|<>~&]/g, (c) => `\\${c}`);
}

/** A story's link as an autolink: http(s) only, nothing that could end or break it. */
function webLink(url: string | null): string | null {
  return url && isWebUrl(url) && !/[\s<>"\x00-\x1f\x7f]/.test(url) ? `<${url}>` : null;
}

export function boardMarkdown({
  pins,
  edges,
  memo,
  now,
}: {
  pins: readonly Pin[];
  edges: readonly BoardEdge[];
  memo: BoardMemo | null;
  now: number;
}): string {
  const number = new Map(pins.map((p, i) => [p.item, i + 1]));
  const lines = [
    "# Orbis investigation board",
    "",
    `Exported ${utcStamp(now)}. ${pins.length} ${pins.length === 1 ? "pin" : "pins"}.`,
    "",
    "Connections mean the pins share a thread, names, a place, coverage or time. " +
      "They don't show cause or wrongdoing.",
    "",
    "## Pins",
    "",
  ];
  pins.forEach((p, i) => {
    const s = p.snapshot;
    lines.push(`${i + 1}. **${pinKindLabel(p.item)}:** ${escapeMarkdown(s.title)}`);
    if (s.place && s.place !== s.title) lines.push(`   - Place: ${escapeMarkdown(s.place)}`);
    const t = s.time ? Date.parse(s.time) : NaN;
    if (Number.isFinite(t)) lines.push(`   - Time: ${utcStamp(t)}`);
    const link = webLink(s.url);
    if (link) lines.push(`   - Link: ${link}`);
  });
  const listed = edges.filter((e) => number.has(e.a) && number.has(e.b));
  if (listed.length > 0) {
    lines.push("", "## Connections", "");
    for (const e of listed) {
      lines.push(`- ${number.get(e.a)} and ${number.get(e.b)}: ${escapeMarkdown(e.label)}`);
    }
  }
  if (memo && !memo.message && memo.sections.length > 0) {
    lines.push("", "## Analysis memo (AI)", "", "Numbers in brackets cite the pins above.");
    for (const s of memo.sections) {
      lines.push("", `### ${escapeMarkdown(s.heading)}`, "", escapeMarkdown(s.text));
    }
  }
  return lines.join("\n") + "\n";
}
