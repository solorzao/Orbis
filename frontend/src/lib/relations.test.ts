import { describe, expect, it } from "vitest";
import contract from "../../e2e/relations.contract.json";
import type { ApiRelationDetail, ApiRelations } from "@/lib/api";
import {
  QUAD_KEYS,
  RELATIONS_UNAVAILABLE,
  quadSide,
  relationArcs,
  relationDays,
  relationDaysWords,
  relationKey,
  relationLensLabel,
  relationPillText,
  relationTag,
  relationWords,
  relationsStatus,
  relationsUnavailable,
  sampleQuad,
  strongestRelations,
  toRelationDetail,
  toRelations,
  type Relation,
} from "@/lib/relations";

const US = { iso: "US", name: "United States", lat: 39.5, lng: -99.06 };
const IR = { iso: "IR", name: "Iran", lat: 32.0, lng: 53.7 };

function rel(over: Partial<Relation> = {}): Relation {
  return {
    a: IR,
    b: US,
    n: 100,
    outlets: 6,
    mentions: 900,
    quad: {
      verbal_cooperation: 10,
      material_cooperation: 5,
      verbal_conflict: 60,
      material_conflict: 25,
    },
    kind: "conflict",
    goldstein: -3.2,
    tone: -4.1,
    from: "US",
    ...over,
  };
}

const colors = {
  cooperation: "#8fb8ff",
  conflict: "#f2949c",
  highlight: "#7fe6ff",
  muted: "rgba(180, 190, 255, 0.10)",
  flowMs: 6000,
};

describe("relationWords", () => {
  it("names the main class when it has half the events", () => {
    expect(relationWords(rel())).toBe("mostly verbal conflict");
  });
  it("falls back to the side with 60% or more", () => {
    const quad = {
      verbal_cooperation: 30,
      material_cooperation: 10,
      verbal_conflict: 35,
      material_conflict: 25,
    };
    expect(relationWords(rel({ quad }))).toBe("mostly conflict");
  });
  it("says mixed in between", () => {
    const quad = {
      verbal_cooperation: 30,
      material_cooperation: 20,
      verbal_conflict: 30,
      material_conflict: 20,
    };
    expect(relationWords(rel({ quad }))).toBe("mixed cooperation and conflict");
  });
});

describe("relationPillText", () => {
  it("counts reported events, from the acting country", () => {
    expect(relationPillText(rel())).toEqual({
      n: 100,
      text: "reported events between United States and Iran, mostly verbal conflict",
    });
  });
  it("is singular for one event", () => {
    expect(relationPillText(rel({ n: 1 })).text).toMatch(/^reported event between/);
  });
});

describe("relationArcs", () => {
  it("colours each arc by its class and starts it at the acting country", () => {
    const [arc] = relationArcs([rel()], { inspected: null, colors, flow: true, muted: false });
    expect(arc.color).toBe(colors.conflict);
    expect([arc.startLat, arc.startLng]).toEqual([US.lat, US.lng]);
    expect(arc.key).toBe("IR-US");
    expect(arc.relation?.n).toBe(100);
    expect(arc.dashGap).toBeGreaterThan(0);
  });
  it("highlights the inspected one", () => {
    const [arc] = relationArcs([rel()], {
      inspected: relationKey("US", "IR"),
      colors,
      flow: false,
      muted: false,
    });
    expect(arc.color).toBe(colors.highlight);
  });
  it("mutes every arc, with no highlight or flow, while another focus leads", () => {
    const [arc] = relationArcs([rel()], { inspected: "IR-US", colors, flow: true, muted: true });
    expect(arc.color).toBe(colors.muted);
    expect(arc.dashGap).toBe(0);
  });
  it("strokes by mentions", () => {
    const arcs = relationArcs([rel(), rel({ a: { ...IR, iso: "IQ" }, mentions: 450 })], {
      inspected: null,
      colors,
      flow: false,
      muted: false,
    });
    expect(arcs.map((a) => a.stroke)).toEqual([0.66, 0.41]);
  });
});

describe("relationDaysWords", () => {
  it("names one UTC day", () =>
    expect(relationDaysWords("2026-10-21", "2026-10-21")).toBe("21 Oct (UTC)"));
  it("names a span", () =>
    expect(relationDaysWords("2026-10-15", "2026-10-21")).toBe("15–21 Oct (UTC days)"));
  it("names a span across months", () =>
    expect(relationDaysWords("2026-09-28", "2026-10-02")).toBe("28 Sep – 2 Oct (UTC days)"));
});

describe("relationLensLabel (the first-week ramp, plan review I4)", () => {
  it("says last 7 days once the lens is covered", () => {
    expect(
      relationLensLabel({ firstDay: "2026-10-15", lastDay: "2026-10-21", since: "2026-10-15" }),
    ).toBe("Relations · last 7 days · 15–21 Oct (UTC days)");
  });
  it("says since a date while the rollups are younger than the lens", () => {
    expect(
      relationLensLabel({ firstDay: "2026-10-15", lastDay: "2026-10-21", since: "2026-10-19" }),
    ).toBe("Relations · since 19 Oct (UTC)");
  });
  it("says last 7 days when there are no rollups at all", () => {
    expect(
      relationLensLabel({ firstDay: "2026-10-15", lastDay: "2026-10-21", since: null }),
    ).toMatch(/^Relations · last 7 days/);
  });
  it("names one relation for the inspector's kicker", () => {
    expect(
      relationLensLabel(
        { firstDay: "2026-10-15", lastDay: "2026-10-21", since: "2026-10-19" },
        "Relation",
      ),
    ).toBe("Relation · since 19 Oct (UTC)");
  });
});

describe("relationsStatus", () => {
  it("says why nothing is drawn, and nothing while loading", () => {
    expect(relationsStatus({ loading: true, error: false, count: 0 })).toBeNull();
    expect(relationsStatus({ loading: false, error: false, count: 0 })).toBe(
      "No reported events between countries in the last 7 days",
    );
    expect(relationsStatus({ loading: false, error: true, count: 0 })).toBe(
      "Relations couldn't load",
    );
    expect(relationsStatus({ loading: false, error: false, count: 3 })).toBeNull();
  });
});

describe("persistent labels (decision 6)", () => {
  it("labels the 5 strongest by mentions", () => {
    const many = Array.from({ length: 7 }, (_, i) =>
      rel({ a: { ...IR, iso: `X${i}` }, mentions: 100 * (i + 1) }),
    );
    expect(strongestRelations(many).map((r) => r.mentions)).toEqual([700, 600, 500, 400, 300]);
  });
  it("puts the class in words, from the acting country", () => {
    expect(relationTag(rel())).toBe("US–IR · 100 · conflict");
  });
});

describe("relationsUnavailable (decision 1)", () => {
  it("is available on any live window, and not under a range or a replay", () => {
    expect(relationsUnavailable({ kind: "live", hours: 1 }, false)).toBeNull();
    expect(relationsUnavailable({ kind: "live", hours: 24 }, true)).toBe(RELATIONS_UNAVAILABLE);
    expect(
      relationsUnavailable(
        { kind: "range", startTime: "2026-10-19T00:00:00Z", endTime: "2026-10-20T00:00:00Z" },
        false,
      ),
    ).toBe(RELATIONS_UNAVAILABLE);
  });
});

describe("the contract's answers (relations.contract.json)", () => {
  it("map to the layer's relations and its lens", () => {
    const { relations, ...lens } = toRelations(contract.list as ApiRelations);
    expect(lens).toEqual({ firstDay: "2026-10-15", lastDay: "2026-10-21", since: "2026-10-15" });
    expect(relations.map((r) => [relationKey(r.a.iso, r.b.iso), r.kind, r.from])).toEqual([
      ["IR-US", "conflict", "US"],
      ["FR-US", "cooperation", "US"],
      ["FR-NG", "cooperation", "FR"],
    ]);
    expect(Object.keys(relations[0].quad)).toEqual([...QUAD_KEYS]);
  });

  it("map the detail, every class and day, its samples in camel case", () => {
    const detail = toRelationDetail(contract.detail as ApiRelationDetail);
    expect(detail.lens).toEqual({
      firstDay: "2026-10-15",
      lastDay: "2026-10-21",
      since: "2026-10-15",
    });
    expect(detail.relation.n).toBe(312);
    expect(detail.directions.map((d) => [d.from, d.to, d.n])).toEqual([
      ["IR", "US", 112],
      ["US", "IR", 200],
    ]);
    expect(detail.daily).toHaveLength(7);
    expect(detail.samples[0]).toEqual({
      url: "https://news.example/2026/10/21/gulf-shipping",
      outlet: "news.example",
      title: "Gulf shipping warnings traded",
      day: "2026-10-21",
      quadClass: 3,
      from: "US",
    });
  });
});

describe("a detail's days and samples", () => {
  const detail = toRelationDetail(contract.detail as ApiRelationDetail);

  it("shows the days from since on: none exist before it", () => {
    expect(relationDays(detail.daily, detail.lens)).toHaveLength(7);
    const ramp = { ...detail.lens, since: "2026-10-19" };
    expect(relationDays(detail.daily, ramp).map((d) => d.day)).toEqual([
      "2026-10-19",
      "2026-10-20",
      "2026-10-21",
    ]);
  });

  it("names a sample's class and its side", () => {
    expect(sampleQuad(3)).toBe("verbal_conflict");
    expect(sampleQuad(2)).toBe("material_cooperation");
    expect(quadSide("material_conflict")).toBe("conflict");
    expect(quadSide("verbal_cooperation")).toBe("cooperation");
  });
});
