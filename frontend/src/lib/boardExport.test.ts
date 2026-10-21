import { describe, it, expect } from "vitest";
import { EXPORT_FILENAME, boardMarkdown, escapeMarkdown } from "./boardExport";
import type { Pin, PinSnapshot } from "./board";
import type { BoardEdge } from "./boardEdges";
import type { BoardMemo } from "./boardApi";

const NOW = Date.parse("2026-10-20T12:05:00Z");
const UUID = "4f6c2a7e-1d2b-4c3d-9e8f-0a1b2c3d4e5f";

function pin(item: string, snapshot: Partial<PinSnapshot>): Pin {
  return {
    item,
    snapshot: { title: "", place: null, lat: null, lng: null, time: null, url: null, ...snapshot },
    x: 0,
    y: 0,
    pinnedAt: 0,
  };
}

const PINS = [
  pin(`article:${UUID}`, {
    title: "France *announces* [new] climate_policy #1",
    place: "Paris, France",
    time: "2026-10-20T11:00:00Z",
    url: "https://example.com/france-climate?a=1&b=2",
  }),
  pin("thread:7", {
    title: "Red Sea shipping attacks",
    place: "Yemen",
    url: "javascript:alert(1)",
  }),
  pin("entity:person:Emmanuel Macron", { title: "Emmanuel Macron", place: "Paris, France" }),
];
const EDGES: BoardEdge[] = [
  { a: PINS[0].item, b: PINS[1].item, kind: "same_thread", label: "same thread" },
  { a: PINS[0].item, b: PINS[2].item, kind: "shared_entity", label: "shared: Emmanuel Macron" },
];
const MEMO: BoardMemo = {
  sections: [
    { heading: "Possible connections", text: "Both cover France [1] [3]." },
    { heading: "Contradictions", text: "None *stated* [2]." },
    { heading: "Open questions", text: "What next? <b>[1]</b>" },
  ],
  citations: [
    { n: 1, item: PINS[0].item },
    { n: 2, item: PINS[1].item },
    { n: 3, item: PINS[2].item },
  ],
  message: null,
  items: PINS.map((p) => p.item),
};

describe("escapeMarkdown", () => {
  it("backslashes everything Markdown could read as syntax", () => {
    expect(escapeMarkdown("*a* _b_ [c](d) #e `f` <g> !h |i ~j 1. -k +l \\m &n")).toBe(
      "\\*a\\* \\_b\\_ \\[c\\]\\(d\\) \\#e \\`f\\` \\<g\\> \\!h \\|i \\~j 1\\. \\-k \\+l \\\\m \\&n",
    );
  });

  it("keeps it on one line", () => {
    expect(escapeMarkdown("one\ntwo\r\nthree")).toBe("one two three");
  });
});

describe("boardMarkdown", () => {
  const md = boardMarkdown({ pins: PINS, edges: EDGES, memo: MEMO, now: NOW });

  it("is named orbis-board.md", () => {
    expect(EXPORT_FILENAME).toBe("orbis-board.md");
  });

  it("lists the pins with their snapshots, escaped, and web links only", () => {
    expect(md).toContain("# Orbis investigation board");
    expect(md).toContain("Exported 20 Oct 2026, 12:05 UTC. 3 pins.");
    expect(md).toContain(
      "1. **Story:** France \\*announces\\* \\[new\\] climate\\_policy \\#1\n" +
        "   - Place: Paris, France\n" +
        "   - Time: 20 Oct 2026, 11:00 UTC\n" +
        "   - Link: <https://example.com/france-climate?a=1&b=2>\n",
    );
    expect(md).toContain("2. **Thread:** Red Sea shipping attacks\n   - Place: Yemen\n");
    expect(md).not.toContain("javascript:");
    expect(md).toContain("3. **Person:** Emmanuel Macron\n");
  });

  it("lists the edges by pin number, and never says they show cause", () => {
    expect(md).toContain("## Connections");
    expect(md).toContain("- 1 and 2: same thread\n- 1 and 3: shared: Emmanuel Macron");
    expect(md).toMatch(/They don't show cause or wrongdoing\./);
    expect(md.toLowerCase()).not.toContain("linked to");
  });

  it("adds the memo, escaped, with its citations as they read", () => {
    expect(md).toContain("## Analysis memo (AI)");
    expect(md).toContain("### Possible connections\n\nBoth cover France \\[1\\] \\[3\\]\\.");
    expect(md).toContain("### Contradictions\n\nNone \\*stated\\* \\[2\\]\\.");
    expect(md).toContain("What next? \\<b\\>\\[1\\]\\</b\\>");
  });

  it("leaves out the memo and connections when there are none", () => {
    const bare = boardMarkdown({ pins: PINS.slice(0, 1), edges: [], memo: null, now: NOW });
    expect(bare).not.toContain("## Connections");
    expect(bare).not.toContain("## Analysis memo");
    expect(bare).toContain("1 pin.");
  });

  it("gives a memo's message instead of its sections", () => {
    const paused = boardMarkdown({
      pins: PINS,
      edges: [],
      memo: { ...MEMO, sections: [], citations: [], message: "AI summaries are paused." },
      now: NOW,
    });
    expect(paused).not.toContain("## Analysis memo");
  });
});
