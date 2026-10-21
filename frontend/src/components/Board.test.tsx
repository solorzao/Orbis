import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import type { ComponentProps } from "react";
import Board from "./Board";
import { decodeShare, type Pin, type PinSnapshot } from "@/lib/board";
import type { BoardEdge } from "@/lib/boardEdges";
import type { BoardMemo } from "@/lib/boardApi";

const UUID = "4f6c2a7e-1d2b-4c3d-9e8f-0a1b2c3d4e5f";

function pin(item: string, x: number, y: number, snapshot: Partial<PinSnapshot>): Pin {
  return {
    item,
    snapshot: { title: "", place: null, lat: null, lng: null, time: null, url: null, ...snapshot },
    x,
    y,
    pinnedAt: 1,
  };
}

const PINS = [
  pin(`article:${UUID}`, 0.5, 0.5, {
    title: "France announces new climate policy",
    place: "Paris, France",
    url: "https://example.com/france-climate",
  }),
  pin("thread:7", 0.1, 0.2, { title: "Red Sea shipping attacks", place: "Yemen" }),
  pin("entity:person:Emmanuel Macron", 0.9, 0.8, { title: "Emmanuel Macron" }),
];
const EDGES: BoardEdge[] = [
  { a: PINS[0].item, b: PINS[1].item, kind: "same_thread", label: "same thread" },
  { a: PINS[0].item, b: PINS[2].item, kind: "shared_entity", label: "shared: Emmanuel Macron" },
];
const MEMO: BoardMemo = {
  sections: [
    { heading: "Possible connections", text: "Both concern France [1] and its president [3]." },
    { heading: "Contradictions", text: "None stated [2]." },
    { heading: "Open questions", text: "What next?" },
  ],
  citations: [
    { n: 1, item: PINS[0].item },
    { n: 2, item: PINS[1].item },
    { n: 3, item: PINS[2].item },
  ],
  message: null,
  items: PINS.map((p) => p.item),
};

type Props = ComponentProps<typeof Board>;
function setup(over: Partial<Props> = {}) {
  const props: Props = {
    variant: "split",
    pins: PINS,
    edges: EDGES,
    coCoverageChecked: true,
    memo: null,
    analyzing: false,
    onAnalyze: vi.fn(),
    onDismissMemo: vi.fn(),
    onMove: vi.fn(),
    onRemove: vi.fn(),
    onClose: vi.fn(),
    ...over,
  };
  return { ...render(<Board {...props} />), props };
}

const card = (name: RegExp | string) => screen.getByRole("group", { name });

describe("Board, the split view", () => {
  it("is the board's dialog: its pins and edges, mirrored on the globe", () => {
    setup();
    const board = screen.getByRole("dialog", { name: "Investigation board" });
    expect(board).toHaveAttribute("aria-modal", "false");
    expect(within(board).getByText("3 pins, mirrored on the globe")).toBeInTheDocument();
    const pins = within(board).getByRole("list", { name: "Pins" });
    expect(
      within(pins)
        .getAllByRole("group")
        .map((g) => g.getAttribute("aria-label")),
    ).toEqual([
      "1. Story, Paris, France: France announces new climate policy",
      "2. Thread, Yemen: Red Sea shipping attacks",
      "3. Person: Emmanuel Macron",
    ]);
    // A story's title links to it (web links only).
    expect(
      within(pins).getByRole("link", { name: "France announces new climate policy" }),
    ).toHaveAttribute("href", "https://example.com/france-climate");
    expect(board).toHaveAttribute("data-edges", "2");
    expect(board.querySelectorAll(".elabel")).toHaveLength(2);
    expect(within(board).getByRole("list", { name: "Connections" })).toHaveTextContent(
      "Pins 1 and 2: same thread",
    );
    const legend = within(board).getByRole("list", { name: "Edge types" });
    expect(
      within(legend)
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual(["Same thread", "Shared names", "Same place", "Covered together", "Close in time"]);
  });

  it("says when co-coverage couldn't be checked", () => {
    setup({ coCoverageChecked: false });
    expect(screen.getByText("Covered together: unavailable right now")).toBeInTheDocument();
  });

  it("moves a focused card with the arrow keys, saying where it is now", () => {
    const { props } = setup();
    const first = card(/^1\. Story/);
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowRight" });
    expect(props.onMove).toHaveBeenCalledWith(PINS[0].item, 0.52, 0.5);
    fireEvent.keyDown(first, { key: "ArrowUp", shiftKey: true });
    expect(props.onMove).toHaveBeenLastCalledWith(PINS[0].item, 0.5, 0.4);
    expect(screen.getByTestId("board-announcer")).toHaveTextContent(
      "Pin 1 moved: 50% across, 40% down",
    );
    fireEvent.keyDown(first, { key: "a" });
    expect(props.onMove).toHaveBeenCalledTimes(2);
  });

  it("drags a card with the pointer, and keeps its place when let go", () => {
    const { props } = setup();
    const first = card(/^1\. Story/);
    first.setPointerCapture = vi.fn();
    fireEvent.pointerDown(first, { button: 0, pointerId: 1, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(first, { pointerId: 1, clientX: 140, clientY: 90 });
    fireEvent.pointerUp(first, { pointerId: 1, clientX: 140, clientY: 90 });
    expect(props.onMove).toHaveBeenCalledTimes(1);
    const [item, x, y] = vi.mocked(props.onMove).mock.calls[0];
    expect(item).toBe(PINS[0].item);
    expect(x).toBeGreaterThan(0.5);
    expect(y).toBeLessThan(0.5);
  });

  it("removes a pin, and closes with its button or Escape", () => {
    const { props } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Remove pin 2: Red Sea shipping attacks" }));
    expect(props.onRemove).toHaveBeenCalledWith("thread:7");
    fireEvent.click(screen.getByRole("button", { name: "Close board" }));
    fireEvent.keyDown(card(/^3\./), { key: "Escape" });
    expect(props.onClose).toHaveBeenCalledTimes(2);
  });

  it("keeps the focus on the board when a pin goes: the next card, else the Close button", () => {
    const { props, rerender } = setup();
    const remove = screen.getByRole("button", { name: "Remove pin 2: Red Sea shipping attacks" });
    remove.focus();
    fireEvent.click(remove);
    rerender(<Board {...props} pins={[PINS[0], PINS[2]]} />);
    expect(card(/^2\. Person/)).toHaveFocus();
    const last = screen.getByRole("button", { name: "Remove pin 2: Emmanuel Macron" });
    last.focus();
    fireEvent.click(last);
    rerender(<Board {...props} pins={[PINS[0]]} />);
    expect(card(/^1\. Story/)).toHaveFocus();
    const only = screen.getByRole("button", { name: /^Remove pin 1/ });
    only.focus();
    fireEvent.click(only);
    rerender(<Board {...props} pins={[]} />);
    expect(screen.getByRole("button", { name: "Close board" })).toHaveFocus();
  });

  it("starts on its Close button", () => {
    setup();
    expect(screen.getByRole("button", { name: "Close board" })).toHaveFocus();
  });

  it("says what to do on an empty board", () => {
    setup({ pins: [], edges: [] });
    expect(screen.getByText("0 pins, mirrored on the globe")).toBeInTheDocument();
    expect(screen.getByText(/Nothing pinned yet/)).toBeInTheDocument();
  });
});

describe("Board, the memo", () => {
  it("Analyze asks for it, and says so while it comes", () => {
    const { props, rerender } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
    expect(props.onAnalyze).toHaveBeenCalled();
    rerender(<Board {...props} analyzing />);
    const button = screen.getByRole("button", { name: "Analyzing…" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(button);
    expect(props.onAnalyze).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("region", { name: "Analysis memo" })).toHaveAttribute(
      "aria-busy",
      "true",
    );
  });

  it("shows the memo's sections; a citation chip focuses its pin", () => {
    setup({ memo: MEMO });
    const memo = screen.getByRole("region", { name: "Analysis memo" });
    expect(
      within(memo)
        .getAllByRole("heading")
        .map((h) => h.textContent),
    ).toEqual(["Possible connections", "Contradictions", "Open questions"]);
    const chip = within(memo).getByRole("button", { name: "Pin 3: Emmanuel Macron" });
    expect(chip).toHaveTextContent("3");
    fireEvent.click(chip);
    expect(card(/^3\. Person/)).toHaveFocus();
    expect(screen.getByTestId("board-announcer")).toHaveTextContent("The analysis memo is ready.");
  });

  it("shows a message instead of the memo, and can be closed", () => {
    const { props } = setup({
      memo: { ...MEMO, sections: [], citations: [], message: "AI summaries are paused." },
    });
    const memo = screen.getByRole("region", { name: "Analysis memo" });
    expect(memo).toHaveTextContent("AI summaries are paused.");
    expect(within(memo).queryByRole("heading")).toBeNull();
    fireEvent.click(within(memo).getByRole("button", { name: "Close memo" }));
    expect(props.onDismissMemo).toHaveBeenCalled();
  });
});

describe("Board, export and share", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setTimeout"] });
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("Export downloads orbis-board.md", async () => {
    let blob: Blob | null = null;
    vi.stubGlobal(
      "URL",
      Object.assign(URL, {
        createObjectURL: vi.fn((b: Blob) => {
          blob = b;
          return "blob:board";
        }),
        revokeObjectURL: vi.fn(),
      }),
    );
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      expect(this.download).toBe("orbis-board.md");
      expect(this.href).toBe("blob:board");
    });
    setup({ memo: MEMO });
    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    expect(clicked).toHaveBeenCalled();
    const text = await blob!.text();
    expect(text).toContain("1. **Story:** France announces new climate policy");
    expect(text).toContain("- 1 and 2: same thread");
    expect(text).toContain("## Analysis memo (AI)");
  });

  it("Share link copies a link to the pins' ids, and shows it", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    setup();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Share link" }));
    });
    const field = screen.getByRole("textbox", { name: "Share link" }) as HTMLInputElement;
    const url = new URL(field.value);
    expect(decodeShare(url.searchParams.get("board"))).toEqual(PINS.map((p) => p.item));
    expect(writeText).toHaveBeenCalledWith(field.value);
    // No pin's text travels in it.
    expect(field.value).not.toMatch(/France|Red%20Sea/);
    expect(screen.getByTestId("board-announcer")).toHaveTextContent("Link copied.");
  });

  it("drops a link shown once the pins change: it would share the old ones", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: () => Promise.resolve() } });
    const { props, rerender } = setup();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Share link" }));
    });
    expect(screen.getByRole("textbox", { name: "Share link" })).toBeInTheDocument();
    rerender(<Board {...props} pins={PINS.map((p) => ({ ...p, x: 0.1 }))} />);
    expect(screen.getByRole("textbox", { name: "Share link" })).toBeInTheDocument();
    rerender(<Board {...props} pins={PINS.slice(1)} />);
    expect(screen.queryByRole("textbox", { name: "Share link" })).toBeNull();
  });

  it("says to copy the link by hand when the clipboard refuses", async () => {
    vi.stubGlobal("navigator", {
      ...navigator,
      clipboard: { writeText: () => Promise.reject(new Error("denied")) },
    });
    setup();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Share link" }));
    });
    expect(screen.getByRole("textbox", { name: "Share link" })).toHaveFocus();
    expect(screen.getByTestId("board-announcer")).toHaveTextContent("Copy the link from the box.");
  });
});

describe("Board, the list view (below 1180px)", () => {
  it("lists the pins with each one's edges under it", () => {
    setup({ variant: "sheet" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("heading", { name: "Investigation board" })).toBeInTheDocument();
    const rows = within(screen.getByRole("list", { name: "Pins" })).getAllByRole("listitem", {
      name: /^\d\./,
    });
    expect(rows).toHaveLength(3);
    const first = within(rows[0]).getByRole("list", { name: "Connections of pin 1" });
    expect(
      within(first)
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual([
      "same thread: 2. Red Sea shipping attacks",
      "shared: Emmanuel Macron: 3. Emmanuel Macron",
    ]);
    expect(within(rows[1]).getByRole("list", { name: "Connections of pin 2" })).toHaveTextContent(
      "same thread: 1. France announces new climate policy",
    );
  });

  it("a citation chip focuses its row", () => {
    setup({ variant: "sheet", memo: MEMO });
    fireEvent.click(screen.getByRole("button", { name: "Pin 2: Red Sea shipping attacks" }));
    expect(screen.getByRole("listitem", { name: /^2\. Thread/ })).toHaveFocus();
  });
});
