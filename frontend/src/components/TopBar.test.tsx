import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import TopBar from "./TopBar";

function setup(over: Partial<Parameters<typeof TopBar>[0]> = {}) {
  const props = {
    activeTopic: "All" as const,
    onTopicChange: vi.fn(),
    isLive: true,
    isLoading: false,
    isOffline: false,
    search: <input aria-label="The pill" />,
    onSearchOpen: vi.fn(),
    searchOpen: false,
    ...over,
  };
  render(<TopBar {...props} />);
  return props;
}

describe("TopBar", () => {
  it("puts the Track search between the topics and the status", () => {
    setup();
    const right = document.querySelector(".topbar-right")!;
    const pill = screen.getByRole("textbox", { name: "The pill" });
    expect(right.firstElementChild).toContainElement(pill);
    const status = screen.getByTestId("status-pill");
    expect(pill.compareDocumentPosition(status) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("has a search button for narrow screens that opens the sheet's search", () => {
    const props = setup();
    const button = screen.getByRole("button", { name: "Track search" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveAttribute("data-testid", "search-open");
    fireEvent.click(button);
    expect(props.onSearchOpen).toHaveBeenCalled();
  });

  it("says when the sheet's search is open", () => {
    setup({ searchOpen: true });
    expect(screen.getByRole("button", { name: "Track search" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });
});
