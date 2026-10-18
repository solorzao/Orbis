import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import HoverCard from "./HoverCard";
import type { ApiPlacePreview } from "@/lib/api";
import type { GlobeLead, GlobePoint } from "@/types/news";
import type { TimeWindow } from "@/lib/timeWindow";

const NOW = Date.parse("2026-10-12T14:30:00Z");
const LIVE: TimeWindow = { kind: "live", hours: 24 };

const LEAD: GlobeLead = {
  title: "France announces new climate policy",
  sourceName: "Reuters",
  publishedAt: "2026-10-12T14:18:00Z",
  imageUrl: "https://images.example.com/paris-climate.jpg",
  topic: "Climate",
  sensitive: false,
};

function point(overrides: Partial<GlobePoint> = {}): GlobePoint {
  return {
    id: "api-0",
    lat: 48.5,
    lng: 2.5,
    size: 1,
    color: "#72ddb2",
    articles: [],
    isCluster: true,
    count: 5,
    topic: "Climate",
    locationName: "Paris, France",
    countryCode: "FR",
    lead: LEAD,
    topicMix: { Climate: 3, Politics: 1, Technology: 1 },
    tone: 0.42,
    ...overrides,
  };
}

const PREVIEW: ApiPlacePreview = {
  spark: [0, 1, 0, 2, 3, 1, 0, 0, 1, 2, 0, 0, 0, 1, 0, 0, 2, 1, 0, 0, 1, 0, 3, 4],
  entities: [
    { name: "Emmanuel Macron", type: "person", n: 4 },
    { name: "European Union", type: "org", n: 3 },
    { name: "Anne Hidalgo", type: "person", n: 2 },
  ],
  brief: "France set new carbon targets as EU leaders met in Paris.",
};

type Props = Partial<Parameters<typeof HoverCard>[0]>;

function renderCard(props: Props = {}) {
  const onReveal = vi.fn();
  const onOpen = vi.fn();
  const utils = render(
    <HoverCard
      point={point()}
      timeWindow={LIVE}
      now={NOW}
      preview={PREVIEW}
      previewLoading={false}
      revealed={new Set()}
      onReveal={onReveal}
      onOpen={onOpen}
      {...props}
    />,
  );
  return { ...utils, onReveal, onOpen, card: screen.getByTestId("hover-card") };
}

describe("HoverCard", () => {
  it("names the place and counts its stories in the window", () => {
    const { card } = renderCard();
    expect(within(card).getByText("Paris, France")).toBeInTheDocument();
    expect(within(card).getByText("FR")).toBeInTheDocument();
    expect(within(card).getByText("5 stories, last 24 h")).toBeInTheDocument();
  });

  it("has a short label, but is no live region (the page announces it)", () => {
    const { card } = renderCard();
    expect(card).not.toHaveAttribute("aria-live");
    expect(card).toHaveAttribute(
      "aria-label",
      "Paris, France: 5 stories. France announces new climate policy",
    );
  });

  it("shows the lead headline with its source and age", () => {
    const { card } = renderCard();
    expect(within(card).getByText("France announces new climate policy")).toHaveClass("hl");
    expect(within(card).getByText("Reuters")).toBeInTheDocument();
    expect(within(card).getByText("12 min ago")).toBeInTheDocument();
  });

  it("shows the topic mix, labelling its top two", () => {
    const { card } = renderCard();
    const bar = card.querySelector(".mix")!;
    expect(bar.querySelectorAll("span")).toHaveLength(3);
    const labels = card.querySelector(".mixl")!;
    expect(labels.textContent).toBe("Climate 60%Politics 20%");
  });

  it("shows the tone on its bar and as a signed score", () => {
    const { card } = renderCard();
    const tone = within(card).getByRole("img", { name: "Headline tone +0.42" });
    expect(tone.querySelector("i")).toHaveStyle({ left: "71%" });
    const score = within(card).getByText("+0.42");
    expect(score).toHaveClass("sent");
    expect(score.getAttribute("style")).toContain("--sc: var(--sentiment-p2)");
  });

  it("adds the sparkline, names and brief once the preview arrives", () => {
    const { card } = renderCard();
    expect(within(card).getByTestId("hover-spark")).toBeInTheDocument();
    const pills = card.querySelectorAll(".chips .pill");
    expect(Array.from(pills, (p) => p.textContent)).toEqual([
      "Emmanuel Macron",
      "European Union",
      "Anne Hidalgo",
    ]);
    // Inert for now: names aren't buttons until they can be tracked.
    expect(within(card).queryByRole("button", { name: "Emmanuel Macron" })).toBeNull();
    const brief = card.querySelector(".brief")!;
    expect(brief).toHaveClass("scrim");
    expect(within(brief as HTMLElement).getByText("AI")).toHaveClass("ai");
    expect(brief.textContent).toContain("France set new carbon targets");
  });

  it("shows a skeleton while the preview loads", () => {
    const { card } = renderCard({ preview: null, previewLoading: true });
    expect(within(card).queryByTestId("hover-spark")).toBeNull();
    expect(card.querySelectorAll(".skel").length).toBeGreaterThan(0);
    expect(card.querySelector(".brief")).toBeNull();
  });

  it("leaves out the brief when nothing is cached, and the names when there are none", () => {
    const { card } = renderCard({ preview: { ...PREVIEW, entities: [], brief: null } });
    expect(within(card).getByTestId("hover-spark")).toBeInTheDocument();
    expect(card.querySelector(".chips")).toBeNull();
    expect(card.querySelector(".brief")).toBeNull();
    expect(card.querySelectorAll(".skel")).toHaveLength(0);
  });

  it("shows no skeleton when the preview failed", () => {
    const { card } = renderCard({ preview: null, previewLoading: false });
    expect(card.querySelectorAll(".skel")).toHaveLength(0);
    expect(within(card).queryByTestId("hover-spark")).toBeNull();
  });

  it("ends with the click hint", () => {
    const { card } = renderCard();
    expect(within(card).getByText("Click to open")).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Open stories" })).toBeNull();
  });

  it("says how many countries the place's country is linked to, while Links is on", () => {
    const { card, rerender } = renderCard({ linkedCountries: 3 });
    const foot = card.querySelector(".foot")!;
    expect(foot).toHaveTextContent("Click to open3 linked countries");
    expect(within(card).getByText("3 linked countries")).toHaveClass("foot-links");

    const props = {
      point: point(),
      timeWindow: LIVE,
      now: NOW,
      preview: PREVIEW,
      previewLoading: false,
      revealed: new Set<string>(),
      onReveal: () => {},
    };
    rerender(<HoverCard {...props} linkedCountries={1} />);
    expect(within(card).getByText("1 linked country")).toBeInTheDocument();
    // Links off (null), or a country with no links: nothing.
    rerender(<HoverCard {...props} linkedCountries={null} />);
    expect(card.querySelector(".foot-links")).toBeNull();
    rerender(<HoverCard {...props} linkedCountries={0} />);
    expect(card.querySelector(".foot-links")).toBeNull();
  });

  it("is a compact card for a place without a lead story", () => {
    const { card } = renderCard({ point: point({ lead: undefined, topicMix: {} }) });
    expect(within(card).getByText("Paris, France")).toBeInTheDocument();
    expect(card.querySelector(".hl")).toBeNull();
    expect(card.querySelector(".thumb")).toBeNull();
    expect(card.querySelector(".mix")).toBeNull();
    expect(within(card).getByRole("img", { name: "Headline tone +0.42" })).toBeInTheDocument();
    expect(card).toHaveAttribute("aria-label", "Paris, France: 5 stories");
  });

  it("names a place without a name by its coordinates", () => {
    const { card } = renderCard({ point: point({ locationName: undefined, countryCode: "" }) });
    expect(within(card).getByText("48.5°, 2.5°")).toBeInTheDocument();
  });
});

describe("HoverCard's image", () => {
  const img = (card: HTMLElement) => card.querySelector<HTMLImageElement>(".thumb img");

  it("loads the lead's https image privately and lazily", () => {
    const { card } = renderCard();
    const image = img(card)!;
    expect(image).toHaveAttribute("src", LEAD.imageUrl);
    expect(image).toHaveAttribute("referrerpolicy", "no-referrer");
    expect(image).toHaveAttribute("loading", "lazy");
    expect(image).toHaveAttribute("decoding", "async");
    expect(image).toHaveAttribute("alt", "");
  });

  it.each([
    ["http", "http://images.example.com/a.jpg"],
    ["a logo", "https://images.example.com/site-logo.png"],
    ["none", null],
  ])("shows the topic glyph instead of %s", (_, imageUrl) => {
    const { card } = renderCard({ point: point({ lead: { ...LEAD, imageUrl } }) });
    expect(img(card)).toBeNull();
    expect(card.querySelector(".thumb.glyph")).toHaveStyle({ "--c": "var(--topic-climate)" });
  });

  it("falls back to the glyph when the image fails to load", () => {
    const { card } = renderCard();
    fireEvent.error(img(card)!);
    expect(img(card)).toBeNull();
    expect(card.querySelector(".thumb.glyph")).not.toBeNull();
  });

  it.each([
    ["tiny", 120, 80],
    ["a banner", 1200, 150],
  ])("falls back to the glyph for a %s image", (_, width, height) => {
    const { card } = renderCard();
    const image = img(card)!;
    Object.defineProperty(image, "naturalWidth", { value: width });
    Object.defineProperty(image, "naturalHeight", { value: height });
    fireEvent.load(image);
    expect(img(card)).toBeNull();
  });

  it("keeps a photo-sized image", () => {
    const { card } = renderCard();
    const image = img(card)!;
    Object.defineProperty(image, "naturalWidth", { value: 640 });
    Object.defineProperty(image, "naturalHeight", { value: 360 });
    fireEvent.load(image);
    expect(img(card)).not.toBeNull();
  });

  it("veils a sensitive lead's image until Show is clicked", () => {
    // Tagged politics then conflict: its topic is Politics, but it is still veiled.
    const conflict = point({ lead: { ...LEAD, topic: "Politics", sensitive: true } });
    const { card, onReveal } = renderCard({ point: conflict });
    expect(card.querySelector(".thumb")).toHaveClass("veiled");
    const show = within(card).getByRole("button", { name: "Conflict image hidden · Show" });
    fireEvent.click(show);
    expect(onReveal).toHaveBeenCalledWith(LEAD.imageUrl);
  });

  it("shows a revealed conflict image", () => {
    const conflict = point({ lead: { ...LEAD, topic: "Conflict", sensitive: true } });
    const { card } = renderCard({ point: conflict, revealed: new Set([LEAD.imageUrl!]) });
    expect(card.querySelector(".thumb")).not.toHaveClass("veiled");
    expect(within(card).queryByRole("button", { name: /Conflict image hidden/ })).toBeNull();
  });
});

describe("HoverCard's image, not sensitive", () => {
  it("shows a lead's image when no tag is conflict", () => {
    const { card } = renderCard({
      point: point({ lead: { ...LEAD, topic: "Conflict", sensitive: false } }),
    });
    expect(card.querySelector(".thumb")).not.toHaveClass("veiled");
  });
});

describe("HoverCard docked (touch)", () => {
  it("offers Open stories instead of the click hint", () => {
    const { card, onOpen } = renderCard({ docked: true });
    expect(card).toHaveClass("docked");
    expect(within(card).queryByText("Click to open")).toBeNull();
    fireEvent.click(within(card).getByRole("button", { name: "Open stories" }));
    expect(onOpen).toHaveBeenCalled();
  });
});
