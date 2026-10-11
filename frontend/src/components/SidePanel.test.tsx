import { describe, it, expect, vi } from "vitest";
import { createRef, useState } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import SidePanel from "./SidePanel";
import type { SideTab } from "@/hooks/useSidePanel";

function Harness({
  initialTab = "copilot",
  initialOpen = true,
  storiesCount,
}: {
  initialTab?: SideTab;
  initialOpen?: boolean;
  storiesCount?: number;
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
      stories={<p>Stories content</p>}
      storiesCount={storiesCount}
    />
  );
}

const panel = () => screen.getByTestId("side-panel");
const tab = (name: string) => screen.getByRole("tab", { name });

describe("SidePanel", () => {
  it("is a labelled region with Co-pilot and Stories tabs", () => {
    render(<Harness />);
    expect(screen.getByRole("region", { name: "Co-pilot and stories" })).toBe(panel());
    expect(panel()).toHaveClass("glass", "side");
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Co-pilot", "Stories"]);
    expect(screen.getByRole("tablist")).toHaveClass("seg");
    expect(screen.getByTestId("side-tab-copilot")).toBe(tab("Co-pilot"));
    expect(screen.getByTestId("side-tab-stories")).toBe(tab("Stories"));
  });

  it("marks the active tab selected, with a roving tabindex", () => {
    render(<Harness initialTab="stories" />);
    expect(tab("Stories")).toHaveAttribute("aria-selected", "true");
    expect(tab("Stories")).toHaveAttribute("tabindex", "0");
    expect(tab("Co-pilot")).toHaveAttribute("aria-selected", "false");
    expect(tab("Co-pilot")).toHaveAttribute("tabindex", "-1");
  });

  it("ties each tab to its panel", () => {
    render(<Harness />);
    for (const name of ["Co-pilot", "Stories"]) {
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
    expect(screen.getByText("Stories content")).not.toBeVisible();

    fireEvent.click(tab("Stories"));
    expect(tab("Stories")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Stories content")).toBeVisible();
    expect(screen.getByText("Co-pilot content")).not.toBeVisible();
  });

  it("moves between tabs with the arrow keys, Home and End", () => {
    render(<Harness />);
    tab("Co-pilot").focus();

    fireEvent.keyDown(tab("Co-pilot"), { key: "ArrowRight" });
    expect(tab("Stories")).toHaveAttribute("aria-selected", "true");
    expect(tab("Stories")).toHaveFocus();

    fireEvent.keyDown(tab("Stories"), { key: "ArrowRight" }); // wraps
    expect(tab("Co-pilot")).toHaveAttribute("aria-selected", "true");
    expect(tab("Co-pilot")).toHaveFocus();

    fireEvent.keyDown(tab("Co-pilot"), { key: "ArrowLeft" }); // wraps back
    expect(tab("Stories")).toHaveFocus();

    fireEvent.keyDown(tab("Stories"), { key: "Home" });
    expect(tab("Co-pilot")).toHaveFocus();
    fireEvent.keyDown(tab("Co-pilot"), { key: "End" });
    expect(tab("Stories")).toHaveFocus();
    expect(tab("Stories")).toHaveAttribute("aria-selected", "true");
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
    render(<Harness initialTab="stories" />);
    fireEvent.click(screen.getByTestId("side-collapse"));
    expect(screen.getByTestId("side-open")).toHaveFocus();

    fireEvent.click(screen.getByTestId("side-open"));
    expect(tab("Stories")).toHaveFocus();
  });

  it("shows a stories badge on the pill only when there are places", () => {
    const { unmount } = render(<Harness initialOpen={false} storiesCount={3} />);
    const pill = screen.getByTestId("side-open");
    expect(pill.querySelector(".num")).toHaveTextContent("3");
    expect(pill).toHaveAccessibleName("Open Co-pilot, 3 places in Stories");
    unmount();

    render(<Harness initialOpen={false} storiesCount={0} />);
    expect(screen.getByTestId("side-open").querySelector(".num")).toBeNull();
    expect(screen.getByTestId("side-open")).toHaveAccessibleName("Open Co-pilot");
  });

  it("opens when a tab is chosen while collapsed (the sheet's tab bar)", () => {
    render(<Harness initialOpen={false} />);
    fireEvent.click(tab("Stories"));
    expect(panel()).toHaveAttribute("data-open", "true");
    expect(tab("Stories")).toHaveAttribute("aria-selected", "true");
  });

  it("lets focus land on a tab panel, and hands out the Stories panel", () => {
    const storiesRef = createRef<HTMLDivElement>();
    render(
      <SidePanel
        tab="stories"
        onTabChange={() => {}}
        open
        onOpenChange={() => {}}
        copilot={null}
        stories={<p>Stories content</p>}
        storiesRef={storiesRef}
      />,
    );
    const stories = screen.getByRole("tabpanel", { name: "Stories" });
    expect(storiesRef.current).toBe(stories);
    expect(stories).toHaveAttribute("tabindex", "-1");
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
        stories={null}
      />,
    );
    fireEvent.click(tab("Stories"));
    expect(onTabChange).toHaveBeenCalledWith("stories");
    expect(onOpenChange).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("side-collapse"));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
