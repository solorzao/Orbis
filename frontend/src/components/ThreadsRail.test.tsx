import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ComponentProps } from "react";
import ThreadsRail from "./ThreadsRail";
import { toThread, type ApiThread, type Thread } from "@/lib/threads";

function thread(id: number, over: Partial<ApiThread> = {}): Thread {
  return toThread({
    id,
    title: `Thread ${id}`,
    synopsis: null,
    status: "developing",
    first_seen: "2026-10-18T06:10:00Z",
    last_seen: "2026-10-18T15:00:00Z",
    n_stories: 14,
    n_sources: 9,
    velocity: 4,
    countries: ["YE", "EG", "NL"],
    places: [],
    topic: "conflict",
    lead: null,
    ...over,
  });
}

const RED_SEA = thread(7, { title: "Red Sea shipping attacks" });

type Props = ComponentProps<typeof ThreadsRail>;
function renderRail(over: Partial<Props> = {}) {
  const props: Props = {
    variant: "rail",
    threads: [RED_SEA],
    status: null,
    loading: false,
    selected: null,
    detail: null,
    lit: null,
    onSelect: vi.fn(),
    ...over,
  };
  return { ...render(<ThreadsRail {...props} />), props };
}

const rows = () =>
  within(screen.getByRole("list", { name: "Developing stories" })).getAllByRole("button");

describe("ThreadsRail", () => {
  it("is a glass panel headed Threads, saying how many are active", () => {
    const threads = Array.from({ length: 12 }, (_, i) => thread(i + 1));
    renderRail({ threads });
    const rail = screen.getByRole("region", { name: "Threads" });
    expect(rail).toHaveClass("glass", "threads");
    expect(rail).toHaveAttribute("data-testid", "threads-rail");
    expect(within(rail).getByRole("heading", { name: "Threads" })).toBeInTheDocument();
    expect(within(rail).getByText("12 active")).toBeInTheDocument();
  });

  it("lists up to 10 threads as buttons, fastest first, as the API orders them", () => {
    const threads = Array.from({ length: 12 }, (_, i) => thread(i + 1));
    renderRail({ threads });
    expect(rows()).toHaveLength(10);
    expect(rows()[0]).toHaveTextContent("Thread 1");
    expect(rows()[9]).toHaveTextContent("Thread 10");
  });

  it("shows each thread's title, stories, status, regions, outlets and velocity", () => {
    const slower = thread(8, { title: "Typhoon nears Luzon", status: "emerging", velocity: 1 });
    renderRail({ threads: [RED_SEA, slower] });
    const [first, second] = rows();
    expect(first).toHaveAccessibleName(
      "Red Sea shipping attacks, Developing, 14 stories, 3 regions, 9 outlets",
    );
    expect(first.querySelector(".th-status")).toHaveAttribute("data-s", "Developing");
    expect(second.querySelector(".th-status")).toHaveAttribute("data-s", "Emerging");
    expect(second).toHaveTextContent("Emerging");
    // The velocity bar: against the fastest listed.
    expect(first.querySelector<HTMLElement>(".bar i")!.style.width).toBe("100%");
    expect(second.querySelector<HTMLElement>(".bar i")!.style.width).toBe("25%");
  });

  it("says why it lists nothing", () => {
    renderRail({ threads: [], status: "No developing stories in this window" });
    expect(screen.getByText("No developing stories in this window")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Developing stories" })).toBeNull();
    expect(screen.queryByText(/active/)).toBeNull();
  });

  it("says it is loading the first time, without a count", () => {
    renderRail({ threads: [], loading: true });
    expect(screen.getByText("Finding developing stories…")).toBeInTheDocument();
    expect(screen.queryByText(/active/)).toBeNull();
  });

  it("selects a thread, and the selected one again deselects it", () => {
    const { props, rerender } = renderRail();
    fireEvent.click(rows()[0]);
    expect(props.onSelect).toHaveBeenCalledWith({ id: 7, title: "Red Sea shipping attacks" });
    expect(rows()[0]).toHaveAttribute("aria-expanded", "false");

    rerender(<ThreadsRail {...props} selected={{ id: 7, title: "Red Sea shipping attacks" }} />);
    expect(rows()[0]).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(rows()[0]);
    expect(props.onSelect).toHaveBeenLastCalledWith(null);
  });

  it("in the sheet, is the tab's list with its count, no panel of its own", () => {
    renderRail({ variant: "sheet", threads: [RED_SEA] });
    expect(screen.queryByRole("region", { name: "Threads" })).toBeNull();
    expect(screen.getByTestId("threads-sheet")).toHaveTextContent("1 active");
    expect(rows()).toHaveLength(1);
  });
});
