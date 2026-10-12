import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import LinkInspector from "./LinkInspector";
import type { LinkDetail, LinkEntry, NewsArticle } from "@/types/news";

const US = { iso: "US", name: "United States", lat: 39.5, lng: -99.06 };
const IR = { iso: "IR", name: "Iran", lat: 32.52, lng: 54.29 };

const NOW = Date.parse("2026-10-12T12:00:00Z");
const minsAgo = (m: number) => new Date(NOW - m * 60_000).toISOString();

function story(over: Partial<NewsArticle> = {}): NewsArticle {
  return {
    id: "s1",
    title: "US and Iran resume indirect nuclear talks in Oman",
    sourceUrl: "https://example.com/talks",
    sourceName: "Reuters",
    publishedAt: minsAgo(18),
    latitude: 38.9,
    longitude: -77.0,
    countryCode: "US",
    region: "Washington, United States",
    topicTags: ["politics"],
    sentimentScore: -0.1,
    ...over,
  };
}

// The backend sends the pair in code order (IR, US), whatever was asked.
const DETAIL: LinkDetail = {
  a: IR,
  b: US,
  n: 43,
  lift: 1.84,
  topicMix: { Politics: 24, Conflict: 12, Economy: 5 },
  tone: -0.32,
  shared: [
    { name: "IAEA", type: "org", n: 9 },
    { name: "State Department", type: "org", n: 6 },
  ],
  themes: ["nuclear talks", "sanctions"],
  articles: [
    story(),
    story({
      id: "s2",
      title: "Tehran rejects new sanctions",
      sourceName: "Al Jazeera",
      sourceUrl: "javascript:alert(1)",
      countryCode: "IR",
      region: "",
      publishedAt: minsAgo(150),
      sentimentScore: -0.48,
    }),
  ],
};

function linkEntry(over: Partial<LinkEntry> = {}): LinkEntry {
  return {
    linkId: "link-IR-US-1",
    // As its arc had it: most of the stories come from the US.
    link: { a: IR, b: US, n: 41, lift: 1.8, topic: "Politics", tone: -0.3, from: "US" },
    query: {
      startTime: "2026-10-11T12:00:00.000Z",
      endTime: "2026-10-12T12:00:00.000Z",
      live: true,
      hours: 24,
    },
    detail: null,
    detailLoading: true,
    explanation: null,
    explaining: false,
    createdAt: NOW,
    ...over,
  };
}

const loaded = (over: Partial<LinkEntry> = {}) =>
  linkEntry({ detail: DETAIL, detailLoading: false, loadedAt: NOW, ...over });

function renderInspector(entry: LinkEntry, handlers: Partial<Record<string, () => void>> = {}) {
  const props = {
    onClose: vi.fn(),
    onMinimize: vi.fn(),
    onExplain: vi.fn(),
    ...handlers,
  };
  render(<LinkInspector entry={entry} {...props} />);
  return props;
}

const readouts = () =>
  within(screen.getByTestId("link-readouts"))
    .getAllByRole("group")
    .map((g) => [g.getAttribute("aria-label"), g.querySelector("b")?.textContent]);

describe("LinkInspector", () => {
  it("names the link from its origin, with the caveat, while its stories load", () => {
    renderInspector(linkEntry());
    const insp = screen.getByTestId("link-inspector");
    expect(insp).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("United States and Iran");
    expect(
      screen.getByText(
        "Named in the same stories. Covered together does not mean cause and effect.",
      ),
    ).toBeVisible();
    expect(screen.getByText("covered together, last 24 h")).toBeVisible();
    // The arc's numbers until the detail lands.
    expect(readouts()).toEqual([
      ["Stories", "41"],
      ["Lift", "1.8×"],
      ["Topic", "Politics"],
      ["Tone", "−0.30"],
    ]);
    expect(screen.getByText("Fetching stories…")).toBeVisible();
  });

  it("shows the detail's readouts, shared names and themes, and its stories", () => {
    renderInspector(loaded());
    expect(screen.getByTestId("link-inspector")).not.toHaveAttribute("aria-busy");
    // The detail comes in code order; the heading keeps the origin first.
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("United States and Iran");
    expect(readouts()).toEqual([
      ["Stories", "43"],
      ["Lift", "1.8×"],
      ["Topic", "Politics"],
      ["Tone", "−0.32"],
    ]);
    const topic = screen.getByText("Politics", { selector: "b" });
    expect(topic.getAttribute("style")).toContain("var(--topic-politics)");

    const shared = within(screen.getByRole("group", { name: "Shared in coverage" }));
    // Inert until the entity tracker (PR 17): not buttons.
    expect(shared.queryAllByRole("button")).toHaveLength(0);
    expect(shared.getByText("IAEA").closest(".pill")).toHaveTextContent("IAEA9");
    expect(shared.getByText("sanctions")).toHaveClass("pill", "pill-theme");

    const list = within(screen.getByRole("list", { name: "Linking stories" }));
    expect(screen.getByText("2 of 43")).toBeVisible();
    const rows = list.getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent(
      "US and Iran resume indirect nuclear talks in OmanReutersWashington18 min agoTone −0.10",
    );
    // The place falls back to the story's country when it has no region.
    expect(rows[1]).toHaveTextContent("Al JazeeraIran2 h 30 min ago");
  });

  it("opens only http(s) stories, in a new tab", () => {
    renderInspector(loaded());
    const link = screen.getByRole("link", { name: /resume indirect nuclear talks/ });
    expect(link).toHaveAttribute("href", "https://example.com/talks");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    // A story whose URL is not http(s) shows its headline, but no link.
    expect(screen.queryByRole("link", { name: /Tehran rejects/ })).toBeNull();
    expect(screen.getByText("Tehran rejects new sanctions")).toBeVisible();
  });

  it("says when no stories came, or they could not load", () => {
    renderInspector(loaded({ detail: { ...DETAIL, articles: [], shared: [], themes: [] } }));
    expect(screen.getByText("No stories link these two in this window.")).toBeVisible();
    expect(screen.queryByRole("group", { name: "Shared in coverage" })).toBeNull();
  });

  it("says when the stories could not load", () => {
    renderInspector(linkEntry({ detailLoading: false, detailError: true }));
    expect(screen.getByText("Couldn't load the stories for this link.")).toBeVisible();
  });

  it("minimizes and closes, and Escape minimizes", () => {
    const { onClose, onMinimize } = renderInspector(loaded());
    fireEvent.click(screen.getByRole("button", { name: "Minimize panel" }));
    expect(onMinimize).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Close panel" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(screen.getByRole("heading", { level: 2 }), { key: "Escape" });
    expect(onMinimize).toHaveBeenCalledTimes(2);
  });

  describe("Explain this link", () => {
    it("asks for an explanation", () => {
      const { onExplain } = renderInspector(loaded());
      const button = screen.getByRole("button", { name: "AI Explain this link" });
      expect(button).toHaveClass("aurora-btn");
      expect(button).toBeEnabled();
      fireEvent.click(button);
      expect(onExplain).toHaveBeenCalledTimes(1);
    });

    it("marks the button unavailable while it loads, keeping it focusable", () => {
      const { onExplain } = renderInspector(loaded({ explaining: true }));
      const button = screen.getByRole("button", { name: "AI Explaining…" });
      // aria-disabled, not disabled: a disabled button would drop the keyboard focus.
      expect(button).not.toBeDisabled();
      expect(button).toHaveAttribute("aria-disabled", "true");
      expect(screen.getByTestId("link-explain")).toHaveAttribute("aria-busy", "true");
      fireEvent.click(button);
      expect(onExplain).not.toHaveBeenCalled();
    });

    it("keeps focus on the button while it loads, then moves it to the explanation", () => {
      const props = { onClose: vi.fn(), onMinimize: vi.fn(), onExplain: vi.fn() };
      const { rerender } = render(<LinkInspector entry={loaded()} {...props} />);
      const button = screen.getByRole("button", { name: "AI Explain this link" });
      button.focus();
      rerender(<LinkInspector entry={loaded({ explaining: true })} {...props} />);
      expect(screen.getByRole("button", { name: "AI Explaining…" })).toHaveFocus();

      rerender(
        <LinkInspector entry={loaded({ explanation: { text: "Talks.", ai: true } })} {...props} />,
      );
      // The button gave way to the text: focus goes there, not to the page.
      const explanation = screen.getByTestId("link-explanation");
      expect(explanation).toHaveFocus();
      expect(explanation).toHaveAttribute("tabindex", "-1");
    });

    it("leaves focus on the button when a message comes instead", () => {
      const props = { onClose: vi.fn(), onMinimize: vi.fn(), onExplain: vi.fn() };
      const { rerender } = render(
        <LinkInspector entry={loaded({ explaining: true })} {...props} />,
      );
      screen.getByRole("button", { name: "AI Explaining…" }).focus();
      rerender(
        <LinkInspector
          entry={loaded({ explanation: { text: "Summary generation failed.", ai: false } })}
          {...props}
        />,
      );
      expect(screen.getByRole("button", { name: "AI Explain this link" })).toHaveFocus();
    });

    it("shows Claude's explanation with the AI badge, in place of the button", () => {
      renderInspector(
        loaded({
          explanation: { text: "Coverage links the two over nuclear talks.", ai: true },
        }),
      );
      const text = screen.getByText("Coverage links the two over nuclear talks.");
      expect(text.querySelector(".ai")).toHaveTextContent("AI");
      expect(screen.queryByRole("button", { name: /Explain this link/ })).toBeNull();
      // Announced when it lands.
      expect(screen.getByTestId("link-explain")).toHaveAttribute("aria-live", "polite");
    });

    it("shows a paused or failed message as plain text, and lets it be asked again", () => {
      renderInspector(
        loaded({
          explanation: {
            text: "AI summaries are paused until 00:00 UTC (daily limit reached).",
            ai: false,
          },
        }),
      );
      const message = screen.getByText(
        "AI summaries are paused until 00:00 UTC (daily limit reached).",
      );
      expect(message.querySelector(".ai")).toBeNull();
      expect(screen.getByRole("button", { name: "AI Explain this link" })).toBeEnabled();
    });
  });
});
