import { describe, it, expect, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { useFlyToThread } from "./useFlyToThread";

const RED_SEA = [
  { lat: 15.5, lng: 48.5 },
  { lat: 30.5, lng: 32.5 },
  { lat: 51.5, lng: 4.5 },
  { lat: -4.5, lng: 39.5 },
];

interface Props {
  id: number | null;
  spread: readonly { lat: number; lng: number }[] | undefined;
}

function setup(initialProps: Props) {
  const fly = vi.fn();
  const grabs = { current: 0 };
  const hook = renderHook(({ id, spread }: Props) => useFlyToThread(id, spread, fly, grabs), {
    initialProps,
  });
  return { ...hook, fly, grabs };
}

describe("useFlyToThread", () => {
  it("flies to a listed thread once, not again on a re-render or when its detail lands", () => {
    const { fly, rerender } = setup({ id: 7, spread: RED_SEA });
    expect(fly).toHaveBeenCalledTimes(1);
    expect(fly.mock.calls[0][0]).toMatchObject({ lat: expect.closeTo(24, 0) });
    rerender({ id: 7, spread: RED_SEA });
    rerender({ id: 7, spread: [...RED_SEA, { lat: 0.5, lng: 32.5 }] }); // the detail's spread
    expect(fly).toHaveBeenCalledTimes(1);
  });

  it("flies again for another thread, and for the same one chosen anew after closing it", () => {
    const { fly, rerender } = setup({ id: 7, spread: RED_SEA });
    rerender({ id: 12, spread: [{ lat: 14.5, lng: 120.5 }] });
    expect(fly).toHaveBeenCalledTimes(2);
    rerender({ id: null, spread: undefined });
    rerender({ id: 12, spread: [{ lat: 14.5, lng: 120.5 }] });
    expect(fly).toHaveBeenCalledTimes(3);
  });

  it("flies to a chip's thread when its places arrive, unless the globe was grabbed since", () => {
    const first = setup({ id: 99, spread: undefined }); // not in the list: no places yet
    expect(first.fly).not.toHaveBeenCalled();
    first.rerender({ id: 99, spread: RED_SEA });
    expect(first.fly).toHaveBeenCalledTimes(1);

    const second = setup({ id: 99, spread: undefined });
    second.grabs.current += 1; // the visitor turned the globe meanwhile
    second.rerender({ id: 99, spread: RED_SEA });
    expect(second.fly).not.toHaveBeenCalled();
  });

  it("goes nowhere for a thread without places", () => {
    const { fly } = setup({ id: 7, spread: [] });
    expect(fly).not.toHaveBeenCalled();
  });
});
