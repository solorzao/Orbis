import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within, waitFor } from "@testing-library/react";
import NewsPanel from "./NewsPanel";
import type { GlobePoint, NewsArticle } from "@/types/news";
import { fetchSelectionSummary } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  fetchSelectionSummary: vi.fn(),
}));

const ago = (h: number) => new Date(Date.now() - h * 3600000).toISOString();

function article(id: string, title: string, score: number, tags: string[]): NewsArticle {
  return {
    id,
    title,
    sourceUrl: `https://example.com/${id}`,
    sourceName: "Reuters",
    publishedAt: ago(2),
    latitude: 48.86,
    longitude: 2.35,
    countryCode: "FR",
    topicTags: tags,
    sentimentScore: score,
  };
}

const ARTICLES = [
  article("a1", "France announces new climate policy", 0.6, ["Climate"]),
  article("a2", "EU leaders meet in Paris for summit", 0, ["Politics"]),
  article("a3", "Paris strikes halt the metro", -0.42, ["Politics"]),
];

function point(overrides: Partial<GlobePoint> = {}): GlobePoint {
  return {
    id: "p1",
    lat: 48.86,
    lng: 2.35,
    size: 1,
    color: "#72ddb2",
    articles: ARTICLES,
    isCluster: true,
    count: 8,
    locationName: "Paris, France",
    topic: "Climate",
    ...overrides,
  };
}

const rows = () => screen.getAllByRole("article");

beforeEach(() => {
  vi.mocked(fetchSelectionSummary).mockReset();
});

describe("NewsPanel", () => {
  it("is the news panel, embedded (no fixed overlay)", () => {
    render(<NewsPanel point={point()} onClose={() => {}} />);
    const panel = screen.getByTestId("news-panel");
    expect(panel).toHaveClass("insp");
    expect(panel.className).not.toMatch(/\bfixed\b/);
  });

  it("names the place as a heading, with the story count", () => {
    render(<NewsPanel point={point()} onClose={() => {}} />);
    expect(screen.getByRole("heading", { level: 2, name: "Paris, France" })).toHaveClass(
      "insp-title",
    );
    expect(screen.getByText("8 stories")).toHaveClass("insp-count");
  });

  it("falls back to coordinates without a place name", () => {
    render(<NewsPanel point={point({ locationName: undefined })} onClose={() => {}} />);
    expect(screen.getByRole("heading", { level: 2, name: "48.86°, 2.35°" })).toBeInTheDocument();
  });

  it("shows the AI summary on a scrim with the AI badge", () => {
    render(<NewsPanel point={point()} onClose={() => {}} clusterSummary="Paris is busy today." />);
    const summary = screen.getByText(/Paris is busy today\./);
    expect(summary.closest(".scrim")).not.toBeNull();
    expect(within(summary).getByText("AI")).toHaveClass("ai");
  });

  it("lists stories as rows: headline link, source, time and signed tone", () => {
    render(<NewsPanel point={point()} onClose={() => {}} />);
    expect(rows()).toHaveLength(3);
    const first = rows()[0];
    expect(first).toHaveClass("art");
    const link = within(first).getByRole("link", { name: "France announces new climate policy" });
    expect(link).toHaveAttribute("href", "https://example.com/a1");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(within(first).getByText("Reuters")).toBeInTheDocument();
    expect(within(first).getByText("2h ago")).toBeInTheDocument();

    const tone = first.querySelector(".sent") as HTMLElement;
    expect(tone).toHaveTextContent("+0.60");
    expect(tone.style.getPropertyValue("--sc")).toBe("var(--sentiment-p3)");
    const negative = rows()[2].querySelector(".sent") as HTMLElement;
    expect(negative).toHaveTextContent("−0.42");
    expect(negative.style.getPropertyValue("--sc")).toBe("var(--sentiment-n2)");
  });

  it("filters by search, topic and tone, with pills that show their state", () => {
    render(<NewsPanel point={point()} onClose={() => {}} />);
    const all = screen.getByRole("button", { name: "All" });
    expect(all).toHaveClass("pill");
    expect(all).toHaveAttribute("aria-pressed", "true");

    fireEvent.change(screen.getByRole("searchbox", { name: "Search headlines" }), {
      target: { value: "summit" },
    });
    expect(rows()).toHaveLength(1);
    expect(screen.getByText("1 of 8 stories")).toBeInTheDocument();
    expect(all).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(all); // clears every filter
    expect(rows()).toHaveLength(3);

    const politics = screen.getByRole("button", { name: "Politics" });
    fireEvent.click(politics);
    expect(politics).toHaveAttribute("aria-pressed", "true");
    expect(rows()).toHaveLength(2);

    const negative = screen.getByRole("button", { name: "Negative" });
    fireEvent.click(negative);
    expect(negative).toHaveAttribute("aria-pressed", "true");
    expect(rows()).toHaveLength(1);
    expect(screen.getByText("Paris strikes halt the metro")).toBeInTheDocument();
  });

  it("says when no story matches the filters", () => {
    render(<NewsPanel point={point()} onClose={() => {}} />);
    fireEvent.change(screen.getByRole("searchbox", { name: "Search headlines" }), {
      target: { value: "nothing like this" },
    });
    expect(screen.getByText("No stories match the selected filters.")).toBeInTheDocument();
  });

  it("summarizes a filtered selection of two or more stories", async () => {
    vi.mocked(fetchSelectionSummary).mockResolvedValue({
      summary: "Two Paris stories.",
      article_count: 2,
    });
    render(<NewsPanel point={point()} onClose={() => {}} />);
    expect(screen.queryByRole("button", { name: /Summarize selection/ })).toBeNull();

    fireEvent.change(screen.getByRole("searchbox", { name: "Search headlines" }), {
      target: { value: "paris" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Summarize selection/ }));

    const summary = await screen.findByText(/Two Paris stories\./);
    expect(summary.closest(".scrim")).not.toBeNull();
    expect(within(summary).getByText("AI")).toHaveClass("ai");
    expect(fetchSelectionSummary).toHaveBeenCalledWith(
      ["EU leaders meet in Paris for summit (Reuters)", "Paris strikes halt the metro (Reuters)"],
      "Paris, France",
    );
  });

  it("offers Load more as a pill while stories remain, with the filters when on", () => {
    const onLoadMore = vi.fn();
    render(<NewsPanel point={point()} onClose={() => {}} onLoadMore={onLoadMore} />);
    const more = screen.getByRole("button", { name: /Load more/ });
    expect(more).toHaveClass("pill");
    expect(more).toHaveTextContent("5 more");
    fireEvent.click(more);
    expect(onLoadMore).toHaveBeenCalledWith(undefined);

    fireEvent.click(screen.getByRole("button", { name: "Climate" }));
    fireEvent.click(screen.getByRole("button", { name: /Load more/ }));
    expect(onLoadMore).toHaveBeenLastCalledWith({
      topics: ["Climate"],
      sentiment: null,
      search: "",
    });
  });

  it("hides Load more once every story is loaded, and disables it while loading", () => {
    const { rerender } = render(<NewsPanel point={point()} onClose={() => {}} loadingMore />);
    expect(screen.getByRole("button", { name: /Loading/ })).toBeDisabled();
    rerender(<NewsPanel point={point({ count: 3 })} onClose={() => {}} />);
    expect(screen.queryByRole("button", { name: /Load more/ })).toBeNull();
  });

  it("minimizes and closes with labelled icon buttons, and Escape minimizes", () => {
    const onClose = vi.fn();
    const onMinimize = vi.fn();
    render(<NewsPanel point={point()} onClose={onClose} onMinimize={onMinimize} />);
    fireEvent.click(screen.getByRole("button", { name: "Minimize panel" }));
    expect(onMinimize).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Close panel" }));
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(screen.getByRole("searchbox", { name: "Search headlines" }), {
      key: "Escape",
    });
    expect(onMinimize).toHaveBeenCalledTimes(2);
  });

  it("ignores Escape and clicks outside the panel", () => {
    const onMinimize = vi.fn();
    render(<NewsPanel point={point()} onClose={() => {}} onMinimize={onMinimize} />);
    fireEvent.keyDown(document.body, { key: "Escape" });
    fireEvent.mouseDown(document.body);
    expect(onMinimize).not.toHaveBeenCalled();
  });

  it("keeps its filters for the place when it unmounts", () => {
    const onFiltersChange = vi.fn();
    const { unmount } = render(
      <NewsPanel point={point()} onClose={() => {}} onFiltersChange={onFiltersChange} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Politics" }));
    unmount();
    expect(onFiltersChange).toHaveBeenLastCalledWith(
      { topics: ["Politics"], sentiment: null, search: "" },
      null,
    );
  });

  it("restores saved filters", () => {
    render(
      <NewsPanel
        point={point()}
        onClose={() => {}}
        savedFilters={{ topics: [], sentiment: "positive", search: "" }}
      />,
    );
    expect(screen.getByRole("button", { name: "Positive" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(rows()).toHaveLength(1);
  });

  it("shows a busy state while the first stories load", () => {
    render(<NewsPanel point={point({ articles: [] })} onClose={() => {}} articlesLoading />);
    expect(screen.getByTestId("news-panel")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText("Fetching stories…")).toBeInTheDocument();
  });

  it("says when a place has no stories", async () => {
    render(<NewsPanel point={point({ articles: [] })} onClose={() => {}} />);
    await waitFor(() =>
      expect(screen.getByText("No stories found for this topic in this area.")).toBeInTheDocument(),
    );
  });
});
