import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ComponentProps } from "react";
import ThreadStories from "./ThreadStories";

const ago = (h: number) => new Date(Date.now() - h * 3600000).toISOString();

const STORY = (k: number) => ({
  title: `Red Sea shipping attacks: report ${k}`,
  sourceName: "Reuters",
  publishedAt: ago(2),
  sourceUrl: `https://example.com/red-sea/${k}`,
  place: "Suez, Egypt",
});

type Props = ComponentProps<typeof ThreadStories>;
function renderStories(over: Partial<Props> = {}) {
  const props: Props = {
    title: "Red Sea shipping attacks",
    total: 24,
    articles: [STORY(1), STORY(2)],
    loading: false,
    loadingMore: false,
    hasMore: false,
    onLoadMore: vi.fn(),
    onClose: vi.fn(),
    ...over,
  };
  return { ...render(<ThreadStories {...props} />), props };
}

describe("ThreadStories", () => {
  it("is a list panel in Inspect: the thread's title and its stories", () => {
    renderStories();
    const panel = screen.getByTestId("thread-stories");
    expect(panel).toHaveClass("insp");
    expect(screen.getByRole("heading", { level: 2, name: "Red Sea shipping attacks" })).toHaveClass(
      "insp-title",
    );
    expect(screen.getByText("24 stories in this thread")).toHaveClass("insp-count");
    const rows = screen.getAllByRole("article");
    expect(rows).toHaveLength(2);
    const link = within(rows[0]).getByRole("link", { name: "Red Sea shipping attacks: report 1" });
    expect(link).toHaveAttribute("href", "https://example.com/red-sea/1");
    expect(link).toHaveAttribute("target", "_blank");
    expect(rows[0]).toHaveTextContent("Reuters");
    expect(rows[0]).toHaveTextContent("2h ago");
    expect(rows[0]).toHaveTextContent("Suez, Egypt");
  });

  it("offers Load more while stories remain", () => {
    const { props, rerender } = renderStories({ hasMore: true });
    fireEvent.click(screen.getByRole("button", { name: /Load more/ }));
    expect(props.onLoadMore).toHaveBeenCalled();
    rerender(<ThreadStories {...props} loadingMore />);
    expect(screen.getByRole("button", { name: "Loading…" })).toBeDisabled();
    rerender(<ThreadStories {...props} hasMore={false} />);
    expect(screen.queryByRole("button", { name: /Load more/ })).toBeNull();
  });

  it("says it is fetching the first stories", () => {
    renderStories({ articles: [], loading: true });
    expect(screen.getByText("Fetching stories…")).toBeInTheDocument();
  });

  it("closes with a labelled button, and Escape", () => {
    const { props } = renderStories();
    fireEvent.click(screen.getByRole("button", { name: "Close panel" }));
    expect(props.onClose).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(screen.getByTestId("thread-stories"), { key: "Escape" });
    expect(props.onClose).toHaveBeenCalledTimes(2);
  });

  it("links only web stories: a javascript: or data: URL renders as plain text", () => {
    renderStories({
      articles: [
        { ...STORY(1), sourceUrl: "javascript:alert(1)" },
        { ...STORY(2), sourceUrl: "data:text/html,<script>alert(1)</script>" },
        { ...STORY(3), sourceUrl: "http://example.com/red-sea/3" },
      ],
    });
    const [js, data, web] = screen.getAllByRole("article");
    expect(within(js).queryByRole("link")).toBeNull();
    expect(js).toHaveTextContent("Red Sea shipping attacks: report 1");
    expect(within(data).queryByRole("link")).toBeNull();
    expect(within(web).getByRole("link")).toHaveAttribute("href", "http://example.com/red-sea/3");
    expect(document.querySelector('a[href^="javascript:"], a[href^="data:"]')).toBeNull();
  });
});
