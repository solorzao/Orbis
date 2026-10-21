import { describe, it, expect, vi } from "vitest";
import { createRef, useState } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import SidePanel from "./SidePanel";
import type { SideTab } from "@/hooks/useSidePanel";

function Harness({
  initialTab = "copilot",
  initialOpen = true,
  inspectCount,
  threads,
}: {
  initialTab?: SideTab;
  initialOpen?: boolean;
  inspectCount?: number;
  threads?: boolean;
}) {
  const [tab, setTab] = useState<SideTab>(initialTab);
  const [open, setOpen] = useState(initialOpen);
  return (
    <SidePanel
      tab={tab}
      onTabChange={setTab}
      open={open}
      onOpenChange={setOpen}
      copilot={<p>Co-pilot content</p>}
      inspect={<p>Inspect content</p>}
      inspectCount={inspectCount}
      threads={threads ? <p>Threads content</p> : undefined}
    />
  );
}

const panel = () => screen.getByTestId("side-panel");
const tab = (name: string) => screen.getByRole("tab", { name });

describe("SidePanel", () => {
  it("is a labelled region with Co-pilot and Inspect tabs", () => {
    render(<Harness />);
    expect(screen.getByRole("region", { name: "Co-pilot and inspector" })).toBe(panel());
    expect(panel()).toHaveClass("glass", "side");
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Co-pilot", "Inspect"]);
    expect(screen.getByRole("tablist")).toHaveClass("seg");
    expect(screen.getByTestId("side-tab-copilot")).toBe(tab("Co-pilot"));
    expect(screen.getByTestId("side-tab-inspect")).toBe(tab("Inspect"));
  });

  it("adds a Threads tab after Inspect when given one (the sheet, below 1180px)", () => {
    render(<Harness threads />);
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual([
      "Co-pilot",
      "Inspect",
      "Threads",
    ]);
    expect(screen.getByTestId("side-tab-threads")).toBe(tab("Threads"));
    expect(screen.queryByText("Threads content")).not.toBeVisible();
    fireEvent.click(tab("Threads"));
    expect(tab("Threads")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Threads content")).toBeVisible();
    expect(screen.getByRole("tabpanel", { name: "Threads" })).toContainElement(
      screen.getByText("Threads content"),
    );
  });

  it("marks the active tab selected, with a roving tabindex", () => {
    render(<Harness initialTab="inspect" />);
    expect(tab("Inspect")).toHaveAttribute("aria-selected", "true");
    expect(tab("Inspect")).toHaveAttribute("tabindex", "0");
    expect(tab("Co-pilot")).toHaveAttribute("aria-selected", "false");
    expect(tab("Co-pilot")).toHaveAttribute("tabindex", "-1");
  });

  it("ties each tab to its panel", () => {
    render(<Harness />);
    for (const name of ["Co-pilot", "Inspect"]) {
      const t = tab(name);
      const panelId = t.getAttribute("aria-controls");
      expect(panelId).toBeTruthy();
      const p = document.getElementById(panelId!);
      expect(p).toHaveAttribute("role", "tabpanel");
      expect(p).toHaveAttribute("aria-labelledby", t.id);
      expect(p).toHaveClass("gbody");
    }
  });

  it("shows only the active tab's content, and clicking a tab switches it", () => {
    render(<Harness />);
    expect(screen.getByText("Co-pilot content")).toBeVisible();
    expect(screen.getByText("Inspect content")).not.toBeVisible();

    fireEvent.click(tab("Inspect"));
    expect(tab("Inspect")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Inspect content")).toBeVisible();
    expect(screen.getByText("Co-pilot content")).not.toBeVisible();
  });

  it("moves between tabs with the arrow keys, Home and End", () => {
    render(<Harness />);
    tab("Co-pilot").focus();

    fireEvent.keyDown(tab("Co-pilot"), { key: "ArrowRight" });
    expect(tab("Inspect")).toHaveAttribute("aria-selected", "true");
    expect(tab("Inspect")).toHaveFocus();

    fireEvent.keyDown(tab("Inspect"), { key: "ArrowRight" }); // wraps
    expect(tab("Co-pilot")).toHaveAttribute("aria-selected", "true");
    expect(tab("Co-pilot")).toHaveFocus();

    fireEvent.keyDown(tab("Co-pilot"), { key: "ArrowLeft" }); // wraps back
    expect(tab("Inspect")).toHaveFocus();

    fireEvent.keyDown(tab("Inspect"), { key: "Home" });
    expect(tab("Co-pilot")).toHaveFocus();
    fireEvent.keyDown(tab("Co-pilot"), { key: "End" });
    expect(tab("Inspect")).toHaveFocus();
    expect(tab("Inspect")).toHaveAttribute("aria-selected", "true");
  });

  it("collapses to a Co-pilot pill and expands back", () => {
    render(<Harness />);
    expect(panel()).toHaveAttribute("data-open", "true");
    expect(screen.queryByTestId("side-open")).not.toBeVisible();

    const collapse = screen.getByTestId("side-collapse");
    expect(collapse).toHaveAccessibleName("Collapse panel");
    expect(collapse).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(collapse);

    expect(panel()).toHaveAttribute("data-open", "false");
    const pill = screen.getByTestId("side-open");
    expect(pill).toBeVisible();
    expect(pill).toHaveClass("pillbar", "pill");
    expect(pill).toHaveTextContent("Co-pilot");
    expect(collapse).toHaveAccessibleName("Expand panel");
    expect(collapse).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(pill);
    expect(panel()).toHaveAttribute("data-open", "true");
    expect(screen.getByTestId("side-open")).not.toBeVisible();
  });

  it("moves focus to the pill on collapse and back to the active tab on expand", () => {
    render(<Harness initialTab="inspect" />);
    fireEvent.click(screen.getByTestId("side-collapse"));
    expect(screen.getByTestId("side-open")).toHaveFocus();

    fireEvent.click(screen.getByTestId("side-open"));
    expect(tab("Inspect")).toHaveFocus();
  });

  it("shows a badge on the pill only when places or links are open", () => {
    const { unmount } = render(<Harness initialOpen={false} inspectCount={3} />);
    const pill = screen.getByTestId("side-open");
    expect(pill.querySelector(".num")).toHaveTextContent("3");
    expect(pill).toHaveAccessibleName("Open Co-pilot, 3 open in Inspect");
    unmount();

    render(<Harness initialOpen={false} inspectCount={0} />);
    expect(screen.getByTestId("side-open").querySelector(".num")).toBeNull();
    expect(screen.getByTestId("side-open")).toHaveAccessibleName("Open Co-pilot");
  });

  it("names the pill after the active tab", () => {
    render(<Harness initialTab="inspect" initialOpen={false} inspectCount={1} />);
    const pill = screen.getByTestId("side-open");
    expect(pill).toHaveTextContent("Inspect");
    expect(pill).toHaveAccessibleName("Open Inspect, 1 open in Inspect");
  });

  it("leaves the default to CSS until the width is known (server render)", () => {
    render(
      <SidePanel
        tab="copilot"
        onTabChange={() => {}}
        open={null}
        onOpenChange={() => {}}
        copilot={null}
        inspect={null}
      />,
    );
    expect(panel()).not.toHaveAttribute("data-open");
    expect(screen.getByTestId("side-open")).not.toBeVisible();
  });

  it("opens when a tab is chosen while collapsed (the sheet's tab bar)", () => {
    render(<Harness initialOpen={false} />);
    fireEvent.click(tab("Inspect"));
    expect(panel()).toHaveAttribute("data-open", "true");
    expect(tab("Inspect")).toHaveAttribute("aria-selected", "true");
  });

  it("lets focus land on a tab panel, and hands out the Inspect panel", () => {
    const inspectRef = createRef<HTMLDivElement>();
    render(
      <SidePanel
        tab="inspect"
        onTabChange={() => {}}
        open
        onOpenChange={() => {}}
        copilot={null}
        inspect={<p>Inspect content</p>}
        inspectRef={inspectRef}
      />,
    );
    const inspect = screen.getByRole("tabpanel", { name: "Inspect" });
    expect(inspectRef.current).toBe(inspect);
    expect(inspect).toHaveAttribute("tabindex", "-1");
  });

  it("reports changes through its callbacks", () => {
    const onTabChange = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <SidePanel
        tab="copilot"
        onTabChange={onTabChange}
        open
        onOpenChange={onOpenChange}
        copilot={null}
        inspect={null}
      />,
    );
    fireEvent.click(tab("Inspect"));
    expect(onTabChange).toHaveBeenCalledWith("inspect");
    expect(onOpenChange).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("side-collapse"));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("shows the sheet's Track search above the tabs' content when given one", () => {
    const { rerender } = render(
      <SidePanel
        tab="copilot"
        onTabChange={() => {}}
        open
        onOpenChange={() => {}}
        copilot={<p>Co-pilot content</p>}
        inspect={<p>Inspect content</p>}
        search={<input aria-label="Sheet search" />}
      />,
    );
    const search = screen.getByTestId("side-search");
    expect(search).toContainElement(screen.getByRole("textbox", { name: "Sheet search" }));
    // Before the panels, after the tab bar.
    const panels = screen.getAllByRole("tabpanel", { hidden: true });
    expect(search.compareDocumentPosition(panels[0]) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
    rerender(
      <SidePanel
        tab="copilot"
        onTabChange={() => {}}
        open
        onOpenChange={() => {}}
        copilot={<p>Co-pilot content</p>}
        inspect={<p>Inspect content</p>}
      />,
    );
    expect(screen.queryByTestId("side-search")).toBeNull();
  });
});
