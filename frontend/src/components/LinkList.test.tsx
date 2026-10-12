import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import LinkList from "./LinkList";
import type { CountryLink } from "@/types/news";

const US = { iso: "US", name: "United States", lat: 39.5, lng: -99.06 };
const IR = { iso: "IR", name: "Iran", lat: 32.52, lng: 54.29 };
const RU = { iso: "RU", name: "Russia", lat: 61.69, lng: 99.22 };
const UA = { iso: "UA", name: "Ukraine", lat: 49.15, lng: 31.23 };

const LINKS: CountryLink[] = [
  { a: RU, b: UA, n: 64, lift: 3.4, topic: "Conflict", tone: -0.5, from: "UA" },
  { a: IR, b: US, n: 1, lift: 1.8, topic: "Politics", tone: -0.3, from: "US" },
];

describe("LinkList", () => {
  it("lists the drawn links in rank order, each a button with its codes, names and stories", () => {
    render(<LinkList links={LINKS} rank="lift" onOpen={() => {}} />);
    const list = screen.getByRole("list", { name: "Links on the globe" });
    const buttons = within(list).getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual([
      "Ukraine and RussiaUA ↔ RU64 stories",
      "United States and IranUS ↔ IR1 story",
    ]);
    // Named as it reads, the visible codes included (WCAG 2.5.3).
    expect(buttons[0]).toHaveAccessibleName("Ukraine and Russia, UA ↔ RU, 64 stories");
    expect(screen.getByText("Most surprising first")).toBeInTheDocument();
  });

  it("says how they are ranked", () => {
    render(<LinkList links={LINKS} rank="count" onOpen={() => {}} />);
    expect(screen.getByText("Most covered first")).toBeInTheDocument();
  });

  it("opens the link picked", () => {
    const onOpen = vi.fn();
    render(<LinkList links={LINKS} rank="lift" onOpen={onOpen} />);
    fireEvent.click(screen.getByRole("button", { name: /^United States and Iran/ }));
    expect(onOpen).toHaveBeenCalledWith(LINKS[1]);
  });

  it("renders nothing without links", () => {
    const { container } = render(<LinkList links={[]} rank="lift" onOpen={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });
});
