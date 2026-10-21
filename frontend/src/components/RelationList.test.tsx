import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import RelationList from "./RelationList";
import { toRelations } from "@/lib/relations";
import type { ApiRelations } from "@/lib/api";
import contract from "../../e2e/relations.contract.json";

const { relations, ...lens } = toRelations(contract.list as ApiRelations);

function renderList(over: Partial<Parameters<typeof RelationList>[0]> = {}) {
  const props = {
    relations,
    lens,
    status: null,
    onOpen: vi.fn(),
    onFocusRelation: vi.fn(),
    ...over,
  };
  render(<RelationList {...props} />);
  return props;
}

describe("RelationList", () => {
  it("lists every relation drawn, under the lens, each named in words", () => {
    renderList();
    expect(screen.getByTestId("relation-list")).toHaveAccessibleName(
      "Relations · last 7 days · 15–21 Oct (UTC days)",
    );
    const list = screen.getByRole("list", { name: "Relations on the globe" });
    const rows = within(list).getAllByRole("button");
    expect(rows.map((r) => r.getAttribute("aria-label"))).toEqual([
      "United States and Iran: 312 reported events, mostly verbal conflict",
      "United States and France: 120 reported events, mostly verbal cooperation",
      "France and Nigeria: 40 reported events, mostly verbal cooperation",
    ]);
    expect(rows.map((r) => r.dataset.relation)).toEqual(["IR-US", "FR-US", "FR-NG"]);
    // The visible words start as the name does (WCAG 2.5.3).
    expect(rows[0]).toHaveTextContent(/^United States and Iran/);
  });

  it("opens the relation picked", () => {
    const { onOpen } = renderList();
    fireEvent.click(screen.getByRole("button", { name: /^France and Nigeria/ }));
    expect(onOpen).toHaveBeenCalledWith(relations[2]);
  });

  it("labels a row's arc while the row has the focus (decision 6, on focus)", () => {
    const { onFocusRelation } = renderList();
    const row = screen.getByRole("button", { name: /^United States and Iran/ });
    fireEvent.focus(row);
    expect(onFocusRelation).toHaveBeenLastCalledWith(relations[0]);
    fireEvent.blur(row);
    expect(onFocusRelation).toHaveBeenLastCalledWith(null);
  });

  it("tabbing from row to row hands the label straight on, with no null between", () => {
    const { onFocusRelation } = renderList();
    const [first, second] = screen.getAllByRole("button");
    fireEvent.focus(first);
    fireEvent.blur(first, { relatedTarget: second });
    fireEvent.focus(second, { relatedTarget: first });
    // Each null would redraw every arc twice (highlight off, then on).
    expect(vi.mocked(onFocusRelation).mock.calls).toEqual([[relations[0]], [relations[1]]]);
  });

  it("without relations, says why, or that they are loading", () => {
    renderList({
      relations: [],
      status: "No reported events between countries in the last 7 days",
    });
    expect(screen.getByTestId("relation-list")).toHaveTextContent(
      "No reported events between countries in the last 7 days",
    );
    expect(screen.queryByRole("list")).toBeNull();
  });

  it("says they are loading before the lens is known", () => {
    renderList({ relations: [], lens: null });
    expect(screen.getByTestId("relation-list")).toHaveTextContent("Loading relations…");
    expect(screen.getByTestId("relation-list")).toHaveAccessibleName("Relations · last 7 days");
  });
});
