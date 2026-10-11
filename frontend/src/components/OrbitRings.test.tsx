import { describe, it, expect, vi } from "vitest";
import { Profiler } from "react";
import { render, waitFor, act } from "@testing-library/react";
import OrbitRings from "./OrbitRings";
import type { GlobeGeometry } from "@/lib/globeView";

const GEOMETRY: GlobeGeometry = { cx: 500, cy: 400, R: 200 };

function nextFrames(n = 3) {
  return act(async () => {
    for (let i = 0; i < n; i++) await new Promise((r) => requestAnimationFrame(() => r(null)));
  });
}

describe("OrbitRings", () => {
  it("draws nothing until the globe reports where it is", async () => {
    const { container } = render(
      <OrbitRings getGeometry={() => null} reduced={false} lowPower={false} />,
    );
    await nextFrames();
    expect(container.querySelector("svg")).toBeNull();
  });

  it("draws the dashed ring with 24 ticks and two tilted orbits", async () => {
    const { container } = render(
      <OrbitRings getGeometry={() => GEOMETRY} reduced={false} lowPower={false} />,
    );
    await waitFor(() => expect(container.querySelector("svg")).not.toBeNull());
    const svg = container.querySelector("svg")!;
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg).toHaveClass("orbits");
    expect(svg.querySelectorAll("line")).toHaveLength(24);
    expect(svg.querySelectorAll("g.orbit")).toHaveLength(2);
    // The dashed ring sits at 1.08R around the globe's centre.
    const ring = svg.querySelector("circle[stroke-dasharray]")!;
    expect(ring).toHaveAttribute("cx", "500");
    expect(ring).toHaveAttribute("r", String(200 * 1.08));
  });

  it("makes every 90-degree tick longer", async () => {
    const { container } = render(
      <OrbitRings getGeometry={() => GEOMETRY} reduced={false} lowPower={false} />,
    );
    await waitFor(() => expect(container.querySelectorAll("line")).toHaveLength(24));
    const lengths = Array.from(container.querySelectorAll("line")).map((l) =>
      Math.hypot(
        Number(l.getAttribute("x2")) - Number(l.getAttribute("x1")),
        Number(l.getAttribute("y2")) - Number(l.getAttribute("y1")),
      ),
    );
    expect(lengths.filter((len) => Math.round(len) === 8)).toHaveLength(4);
    expect(lengths.filter((len) => Math.round(len) === 4)).toHaveLength(20);
  });

  it("hides each orbit's far side behind the globe", async () => {
    const { container } = render(
      <OrbitRings getGeometry={() => GEOMETRY} reduced={false} lowPower={false} />,
    );
    await waitFor(() => expect(container.querySelectorAll("g.orbit")).toHaveLength(2));
    const mask = container.querySelector("mask")!;
    const masked = container.querySelectorAll(`path[mask="url(#${mask.id})"]`);
    expect(masked).toHaveLength(2);
  });

  it("flies a satellite on each orbit", async () => {
    const { container } = render(
      <OrbitRings getGeometry={() => GEOMETRY} reduced={false} lowPower={false} />,
    );
    await waitFor(() => expect(container.querySelectorAll("animateMotion")).toHaveLength(2));
  });

  it.each([
    { reduced: true, lowPower: false },
    { reduced: false, lowPower: true },
  ])("has no satellites when reduced=$reduced, lowPower=$lowPower", async (motion) => {
    const { container } = render(<OrbitRings getGeometry={() => GEOMETRY} {...motion} />);
    await waitFor(() => expect(container.querySelectorAll("g.orbit")).toHaveLength(2));
    expect(container.querySelectorAll("animateMotion")).toHaveLength(0);
  });

  it("re-renders when the globe moves a pixel, not on sub-pixel jitter", async () => {
    let geometry: GlobeGeometry = { ...GEOMETRY };
    const onRender = vi.fn();
    const { container } = render(
      <Profiler id="orbits" onRender={onRender}>
        <OrbitRings getGeometry={() => geometry} reduced={false} lowPower={false} />
      </Profiler>,
    );
    await waitFor(() => expect(container.querySelector("svg")).not.toBeNull());
    const commits = onRender.mock.calls.length;

    geometry = { cx: 500.2, cy: 399.9, R: 200.3 };
    await nextFrames(5);
    expect(onRender.mock.calls.length).toBe(commits);

    geometry = { cx: 500, cy: 400, R: 250 };
    await waitFor(() =>
      expect(container.querySelector("circle[stroke-dasharray]")).toHaveAttribute(
        "r",
        String(250 * 1.08),
      ),
    );
  });

  it("stops polling the globe after unmount", async () => {
    const getGeometry = vi.fn(() => GEOMETRY);
    const { unmount } = render(
      <OrbitRings getGeometry={getGeometry} reduced={false} lowPower={false} />,
    );
    await nextFrames();
    unmount();
    const calls = getGeometry.mock.calls.length;
    await nextFrames();
    expect(getGeometry.mock.calls.length).toBe(calls);
  });
});
