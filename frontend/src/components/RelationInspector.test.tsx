import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import RelationInspector from "./RelationInspector";
import { toRelationDetail, toRelations, type RelationDetail } from "@/lib/relations";
import type { ApiRelationDetail, ApiRelations } from "@/lib/api";
import type { RelationEntry } from "@/types/news";
import contract from "../../e2e/relations.contract.json";

const LIST = toRelations(contract.list as ApiRelations);
const CONFLICT = toRelations(contract.list_conflict as ApiRelations);
const DETAIL = toRelationDetail(contract.detail as ApiRelationDetail);
const LENS = { firstDay: LIST.firstDay, lastDay: LIST.lastDay, since: LIST.since };

function entry(over: Partial<RelationEntry> = {}): RelationEntry {
  return {
    relationId: "relation-IR-US-1",
    relation: LIST.relations[0],
    filter: "all",
    lens: LENS,
    detail: DETAIL,
    detailLoading: false,
    createdAt: 1,
    ...over,
  };
}

function renderInspector(e: RelationEntry) {
  const onClose = vi.fn();
  const onMinimize = vi.fn();
  const view = render(<RelationInspector entry={e} onClose={onClose} onMinimize={onMinimize} />);
  return { ...view, onClose, onMinimize };
}

const readout = (name: string) => screen.getByRole("group", { name });

describe("RelationInspector", () => {
  it("shows the arc's numbers before the detail lands, named from the acting country", () => {
    renderInspector(entry({ detail: null, detailLoading: true }));
    const inspector = screen.getByTestId("relation-inspector");
    expect(inspector).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("United States and Iran");
    expect(readout("Events")).toHaveTextContent("312");
    expect(readout("Outlets")).toHaveTextContent("23");
    // A lower bound (each day and class keeps up to 8 outlets), said in words.
    expect(readout("Outlets")).toHaveTextContent("at least");
    expect(readout("Goldstein")).toHaveTextContent("−3.1");
    expect(readout("Goldstein")).toHaveTextContent(
      "event-type score, −10 conflict to +10 cooperation",
    );
    expect(readout("Tone")).toHaveTextContent("−4.2");
    // No report count anywhere (plan review I1).
    const readouts = within(screen.getByTestId("relation-readouts")).getAllByRole("group");
    expect(readouts.map((r) => r.getAttribute("aria-label"))).toEqual([
      "Events",
      "Outlets",
      "Goldstein",
      "Tone",
    ]);
  });

  it("says what the events are: machine-coded, reported, not verified", () => {
    renderInspector(entry());
    expect(screen.getByTestId("relation-inspector")).toHaveTextContent(
      "Events GDELT machine-coded from news reports: who did what to whom, as reported. Not verified facts; one report can yield several events.",
    );
  });

  it("shows every class, whatever the layer's class switch says (decision 7)", () => {
    // Opened under Conflict: the arc's numbers are conflict's, the detail every class's.
    renderInspector(entry({ relation: CONFLICT.relations[0], filter: "conflict" }));
    expect(screen.queryByText(/only, as the class switch filters/)).toBeNull();
    const classes = screen.getByRole("list", { name: "Reported events by class" });
    expect(
      within(classes)
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual([
      "Verbal cooperation4013%",
      "Material cooperation124%",
      "Verbal conflict21067%",
      "Material conflict5016%",
    ]);
    expect(readout("Events")).toHaveTextContent("312"); // the detail's, every class
  });

  it("names each direction's events in words", () => {
    renderInspector(entry());
    const directions = screen.getByRole("list", { name: "Directions" });
    expect(
      within(directions)
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual([
      "Iran → United States: 112 events, mostly verbal conflict",
      "United States → Iran: 200 events, mostly verbal conflict",
    ]);
  });

  it("breaks the lens down by UTC day: all 7 days once it is covered", () => {
    renderInspector(entry());
    expect(screen.getByText("Relation · last 7 days · 15–21 Oct (UTC days)")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Reported events by UTC day" });
    const rows = within(table).getAllByRole("row").slice(1); // the header first
    expect(rows).toHaveLength(7);
    expect(rows[0]).toHaveTextContent("15 Oct630");
  });

  it("shows only the days from since during the first week's ramp", () => {
    const ramp: RelationDetail = { ...DETAIL, lens: { ...DETAIL.lens, since: "2026-10-19" } };
    renderInspector(entry({ detail: ramp }));
    expect(screen.getByText("Relation · since 19 Oct (UTC)")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Reported events by UTC day" });
    expect(within(table).getAllByRole("row").slice(1)).toHaveLength(3);
  });

  it("lists sample reports, linking only web URLs, safely", () => {
    const samples = DETAIL.samples.map((s, i) =>
      i === 0 ? { ...s, url: "javascript:alert(1)" } : s,
    );
    renderInspector(entry({ detail: { ...DETAIL, samples } }));
    const list = screen.getByRole("list", { name: "Sample reports" });
    // The first sample's URL isn't http(s): its title is text, not a link.
    expect(within(list).getByText("Gulf shipping warnings traded").closest("a")).toBeNull();
    expect(screen.queryByRole("link", { name: "Gulf shipping warnings traded" })).toBeNull();
    // A sample with no title of ours is named by its outlet.
    const link = screen.getByRole("link", { name: "wire.example" });
    expect(link).toHaveAttribute("href", "https://wire.example/2026/10/20/talks");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    const first = within(list).getAllByRole("listitem")[0];
    expect(first).toHaveTextContent("news.example");
    expect(first).toHaveTextContent("21 Oct");
    expect(first).toHaveTextContent("Verbal conflict");
    expect(first).toHaveTextContent("United States → Iran");
  });

  it("says a pair with no events left in the lens as text, not an error", () => {
    renderInspector(entry({ detail: null, notFound: true }));
    const inspector = screen.getByTestId("relation-inspector");
    expect(inspector).toHaveTextContent("No reported events between them in the last 7 days.");
    expect(screen.queryByRole("list", { name: "Reported events by class" })).toBeNull();
    expect(screen.getByRole("button", { name: "Close panel" })).toBeInTheDocument();
  });

  it("says when the detail couldn't load", () => {
    renderInspector(entry({ detail: null, detailError: true }));
    expect(screen.getByTestId("relation-inspector")).toHaveTextContent(
      "Couldn't load this relation's detail.",
    );
  });

  it("labels a filtered arc's numbers as one class's until every class loads (or if it fails)", () => {
    for (const over of [{ detailLoading: true }, { detailError: true }]) {
      const { unmount } = renderInspector(
        entry({ relation: CONFLICT.relations[0], filter: "conflict", detail: null, ...over }),
      );
      expect(readout("Events")).toHaveTextContent("260"); // conflict's alone
      expect(screen.getByText("Conflict only, as the class switch filters it")).toBeVisible();
      // No class rows from one class's numbers: they would read as the pair's split.
      expect(screen.queryByRole("list", { name: "Reported events by class" })).toBeNull();
      unmount();
    }
  });

  it("skips the class of a sample whose QuadClass isn't 1 to 4, and still lists it", () => {
    const samples = DETAIL.samples.map((s, i) =>
      i === 0 ? { ...s, quadClass: 7 as unknown as 1 } : s,
    );
    renderInspector(entry({ detail: { ...DETAIL, samples } }));
    const [first] = within(screen.getByRole("list", { name: "Sample reports" })).getAllByRole(
      "listitem",
    );
    expect(first).toHaveTextContent("Gulf shipping warnings traded");
    expect(first.querySelector(".art-tag")).toBeNull();
  });

  it("minimizes on Escape, closes on Close, and has no Pin (decision 9)", () => {
    const { onClose, onMinimize } = renderInspector(entry());
    fireEvent.keyDown(screen.getByRole("heading", { level: 2 }), { key: "Escape" });
    expect(onMinimize).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Minimize panel" }));
    expect(onMinimize).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole("button", { name: "Close panel" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: /pin/i })).toBeNull();
  });

  it("never says linked, caused or attacked", () => {
    const { container } = renderInspector(entry());
    expect(container.textContent).not.toMatch(/linked|caus|attack/i);
    const { container: loading } = renderInspector(entry({ detail: null, detailLoading: true }));
    expect(loading.textContent).not.toMatch(/linked|caus|attack/i);
  });
});
