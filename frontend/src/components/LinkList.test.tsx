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
    render(<LinkList links={LINKS} rank="lift" status={null} onOpen={() => {}} />);
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
    render(<LinkList links={LINKS} rank="count" status={null} onOpen={() => {}} />);
    expect(screen.getByText("Most covered first")).toBeInTheDocument();
  });

  it("opens the link picked", () => {
    const onOpen = vi.fn();
    render(<LinkList links={LINKS} rank="lift" status={null} onOpen={onOpen} />);
    fireEvent.click(screen.getByRole("button", { name: /^United States and Iran/ }));
    expect(onOpen).toHaveBeenCalledWith(LINKS[1]);
  });

  it("without links, says why (the Links status), or that they are loading", () => {
    const { rerender } = render(
      <LinkList links={[]} rank="lift" status="No links in this window" onOpen={() => {}} />,
    );
    expect(screen.getByTestId("link-list")).toHaveTextContent("No links in this window");
    expect(screen.queryByRole("list")).toBeNull();
    rerender(<LinkList links={[]} rank="lift" status={null} onOpen={() => {}} />);
    expect(screen.getByTestId("link-list")).toHaveTextContent("Loading links…");
  });

  describe("focus while the links change", () => {
    const [RU_UA, IR_US] = LINKS;
    const SA_YE: CountryLink = {
      a: { iso: "SA", name: "Saudi Arabia", lat: 24.12, lng: 44.52 },
      b: { iso: "YE", name: "Yemen", lat: 15.91, lng: 47.54 },
      n: 46,
      lift: 6.2,
      topic: "Conflict",
      tone: -0.5,
      from: "SA",
    };
    const row = (name: RegExp) => screen.getByRole("button", { name });
    const list = (links: CountryLink[]) => (
      <LinkList links={links} rank="lift" status={null} onOpen={() => {}} />
    );

    it("stays on a focused row that is still listed (a new rank or window)", () => {
      const { rerender } = render(list([RU_UA, IR_US]));
      row(/^United States and Iran/).focus();
      rerender(list([IR_US, SA_YE]));
      expect(row(/^United States and Iran/)).toHaveFocus();
    });

    it("moves to the first row when the focused row drops out", () => {
      const { rerender } = render(list([RU_UA, IR_US]));
      row(/^United States and Iran/).focus();
      rerender(list([SA_YE, RU_UA]));
      expect(row(/^Saudi Arabia and Yemen/)).toHaveFocus();
    });

    it("moves to the list itself when no links are left", () => {
      const { rerender } = render(list([RU_UA, IR_US]));
      row(/^United States and Iran/).focus();
      rerender(
        <LinkList links={[]} rank="lift" status="No links in this window" onOpen={() => {}} />,
      );
      const listBox = screen.getByTestId("link-list");
      expect(listBox).toHaveFocus();
      expect(listBox).toHaveAttribute("tabindex", "-1");
      expect(listBox).toHaveAccessibleName("Links on the globe");
    });

    it("leaves the focus alone when it is outside the list", () => {
      const elsewhere = document.createElement("button");
      document.body.appendChild(elsewhere);
      const { rerender } = render(list([RU_UA, IR_US]));
      elsewhere.focus();
      rerender(list([SA_YE]));
      expect(elsewhere).toHaveFocus();
      elsewhere.remove();
    });
  });
});
