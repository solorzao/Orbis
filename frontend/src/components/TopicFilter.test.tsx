import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import TopicFilter from "./TopicFilter";

const TOPICS = ["All", "Politics", "Conflict", "Technology", "Climate", "Economy", "Health"];

describe("TopicFilter", () => {
  it("is a labelled nav of topic pills", () => {
    render(<TopicFilter activeTopic="All" onTopicChange={() => {}} />);
    const nav = screen.getByRole("navigation", { name: "Topic filter" });
    expect(nav).toHaveAttribute("data-testid", "topic-filter");
    const buttons = within(nav).getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(TOPICS);
    buttons.forEach((b) => expect(b).toHaveClass("pill"));
  });

  it("marks only the active topic as pressed", () => {
    render(<TopicFilter activeTopic="Climate" onTopicChange={() => {}} />);
    for (const topic of TOPICS) {
      expect(screen.getByRole("button", { name: topic })).toHaveAttribute(
        "aria-pressed",
        String(topic === "Climate"),
      );
    }
  });

  it("calls onTopicChange with the clicked topic", () => {
    const onTopicChange = vi.fn();
    render(<TopicFilter activeTopic="All" onTopicChange={onTopicChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Economy" }));
    expect(onTopicChange).toHaveBeenCalledWith("Economy");
  });

  it("colours each topic's dot from its token; All has no dot", () => {
    render(<TopicFilter activeTopic="All" onTopicChange={() => {}} />);
    expect(screen.getByRole("button", { name: "All" }).querySelector(".dot")).toBeNull();
    const dot = screen.getByRole("button", { name: "Technology" }).querySelector(".dot");
    expect(dot).toHaveAttribute("aria-hidden", "true");
    expect((dot as HTMLElement).style.getPropertyValue("--c")).toBe("var(--topic-technology)");
  });
});
