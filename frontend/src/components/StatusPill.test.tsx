import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import StatusPill from "./StatusPill";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("StatusPill clock", () => {
  it("shows the time as HH:MM in UTC", () => {
    vi.setSystemTime(new Date("2026-10-11T07:05:42Z"));
    render(<StatusPill isLive isLoading={false} isOffline={false} />);
    expect(screen.getByText("07:05")).toBeInTheDocument();
    expect(screen.getByText("UTC")).toBeInTheDocument();
  });

  it("uses UTC, not local time, around midnight", () => {
    vi.setSystemTime(new Date("2026-10-11T23:59:10Z"));
    render(<StatusPill isLive isLoading={false} isOffline={false} />);
    expect(screen.getByText("23:59")).toBeInTheDocument();
  });

  it("updates every 30 seconds", () => {
    vi.setSystemTime(new Date("2026-10-11T07:05:42Z"));
    render(<StatusPill isLive isLoading={false} isOffline={false} />);

    act(() => {
      vi.advanceTimersByTime(29_000);
    });
    // 07:06:11 now, but the clock hasn't ticked yet.
    expect(screen.getByText("07:05")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1_000);
    });
    expect(screen.getByText("07:06")).toBeInTheDocument();
  });
});

describe("StatusPill state", () => {
  it("is findable for the layout test", () => {
    render(<StatusPill isLive isLoading={false} isOffline={false} />);
    expect(screen.getByTestId("status-pill")).toBeInTheDocument();
  });

  it("shows Live", () => {
    render(<StatusPill isLive isLoading={false} isOffline={false} />);
    expect(screen.getByText("Live")).toHaveClass("live");
  });

  it("shows Loading… while loading", () => {
    render(<StatusPill isLive={false} isLoading isOffline={false} />);
    expect(screen.getByText("Loading…")).toHaveClass("muted");
    expect(screen.queryByText("Live")).toBeNull();
  });

  it("shows Offline when the API is down, over any other state", () => {
    render(<StatusPill isLive isLoading isOffline />);
    expect(screen.getByText("Offline")).toHaveClass("offline");
    expect(screen.queryByText("Live")).toBeNull();
    expect(screen.queryByText("Loading…")).toBeNull();
  });

  it("announces the state, not the clock, through a status region", () => {
    vi.setSystemTime(new Date("2026-10-11T07:05:42Z"));
    const { rerender } = render(<StatusPill isLive={false} isLoading isOffline={false} />);
    const region = screen.getByRole("status");
    expect(region).toHaveTextContent("Loading…");
    expect(region).not.toHaveTextContent("07:05");

    rerender(<StatusPill isLive isLoading={false} isOffline={false} />);
    // Same region, new text: screen readers read the change.
    expect(screen.getByRole("status")).toBe(region);
    expect(region).toHaveTextContent("Live");
  });

  it("keeps the status region mounted while it has nothing to say", () => {
    render(<StatusPill isLive={false} isLoading={false} isOffline={false} />);
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("shows only the clock for a past day (not live, loaded, online)", () => {
    vi.setSystemTime(new Date("2026-10-11T07:05:42Z"));
    render(<StatusPill isLive={false} isLoading={false} isOffline={false} />);
    expect(screen.getByText("07:05")).toBeInTheDocument();
    expect(screen.queryByText("Live")).toBeNull();
    expect(screen.queryByText("Loading…")).toBeNull();
    expect(screen.queryByText("Offline")).toBeNull();
  });
});
