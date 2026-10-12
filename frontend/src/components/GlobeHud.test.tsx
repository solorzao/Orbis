import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createRef } from "react";
import { act, render } from "@testing-library/react";
import GlobeHud from "./GlobeHud";
import type { Box, Chrome } from "@/lib/hoverCard";
import type { GlobePoint } from "@/types/news";

const PARIS: GlobePoint = {
  id: "api-0",
  lat: 48.5,
  lng: 2.5,
  size: 1,
  color: "#72ddb2",
  articles: [],
  isCluster: true,
  count: 5,
  topic: "Climate",
};

// Frames run by hand: the loop's callbacks queue here.
let frames: Map<number, FrameRequestCallback>;
let nextId: number;

beforeEach(() => {
  frames = new Map();
  nextId = 1;
  vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
    frames.set(nextId, cb);
    return nextId++;
  });
  vi.spyOn(window, "cancelAnimationFrame").mockImplementation((id) => {
    frames.delete(id);
  });
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1440 });
  Object.defineProperty(window, "innerHeight", { configurable: true, value: 900 });
});

afterEach(() => {
  vi.restoreAllMocks();
});

function runFrame(time = 1000) {
  const pending = [...frames.entries()];
  frames.clear();
  act(() => pending.forEach(([, cb]) => cb(time)));
}

/** The card the HUD places: a fixed-size element. */
function cardElement() {
  const el = document.createElement("article");
  Object.defineProperty(el, "offsetWidth", { value: 340 });
  Object.defineProperty(el, "offsetHeight", { value: 300 });
  document.body.appendChild(el);
  const ref = createRef<HTMLElement>();
  (ref as { current: HTMLElement | null }).current = el;
  return { el, ref };
}

const NO_CHROME: Chrome = { top: [], side: [], bottom: [] };

function renderHud(props: Partial<Parameters<typeof GlobeHud>[0]> = {}) {
  const { el, ref } = cardElement();
  const project = vi.fn(() => ({ x: 600, y: 400 }));
  const utils = render(
    <GlobeHud
      point={PARIS}
      project={project}
      getGeometry={() => ({ cx: 720, cy: 450, R: 300 })}
      cardRef={ref}
      docked={false}
      reduced={false}
      getChrome={() => NO_CHROME}
      {...props}
    />,
  );
  return { ...utils, el, project };
}

describe("GlobeHud", () => {
  it("runs no frame loop while no card is shown", () => {
    const { container } = renderHud({ point: null });
    expect(window.requestAnimationFrame).not.toHaveBeenCalled();
    expect(container.querySelector("circle")).toBeNull();
  });

  it("locks a reticle onto the dot and places the card beside it", () => {
    const { container, el, project } = renderHud();
    runFrame(1000);
    runFrame(1000 + 380);

    expect(project).toHaveBeenCalledWith(48.5, 2.5);
    const svg = container.querySelector("svg.hud")!;
    expect(svg).toHaveAttribute("aria-hidden", "true");
    const [ring] = svg.querySelectorAll("circle");
    expect(ring).toHaveAttribute("cx", "600");
    expect(ring).toHaveAttribute("cy", "400");
    expect(ring).toHaveAttribute("r", "14");
    expect(svg.querySelectorAll("line")).toHaveLength(4);

    // Left of the globe's centre: the card goes on the dot's left.
    expect(el.style.left).toBe(`${600 - 48 - 340}px`);
    expect(el.style.top).toBe(`${400 - 135}px`);
    expect(el.dataset.placed).toBe("true");
    // A curved leader from the reticle to the card's right edge.
    expect(svg.querySelector("path.leader")!.getAttribute("d")).toMatch(/^M575 400 C .* 552 400$/);
  });

  it("keeps the card off the chrome it is given", () => {
    const panel: Box = { left: 0, top: 0, right: 560, bottom: 900 };
    const { el } = renderHud({ getChrome: () => ({ ...NO_CHROME, side: [panel] }) });
    runFrame();
    expect(Number.parseFloat(el.style.left)).toBe(600 + 48);
  });

  it("follows the dot as the globe turns", () => {
    const { container, project } = renderHud();
    runFrame(1000);
    project.mockReturnValue({ x: 640, y: 380 });
    runFrame(1016);
    expect(container.querySelector("circle")).toHaveAttribute("cx", "640");
  });

  it("closes the reticle in as it locks on, at once with reduced motion", () => {
    const { container, rerender } = renderHud();
    runFrame(1000);
    expect(container.querySelector("circle")).toHaveAttribute("r", "22");
    rerender(
      <GlobeHud
        point={PARIS}
        project={() => ({ x: 600, y: 400 })}
        getGeometry={() => ({ cx: 720, cy: 450, R: 300 })}
        cardRef={{ current: null }}
        docked={false}
        reduced
        getChrome={() => NO_CHROME}
      />,
    );
    runFrame(1000);
    expect(container.querySelector("circle")).toHaveAttribute("r", "14");
  });

  it("hides the card while its dot is on the far side of the globe", () => {
    const { container, el, project } = renderHud();
    runFrame();
    project.mockReturnValue(null as unknown as { x: number; y: number });
    runFrame();
    expect(container.querySelector("circle")).toBeNull();
    expect(el.dataset.placed).toBeUndefined();
  });

  it("docks the card above the bottom chrome on a touch screen, with no leader", () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 390 });
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 844 });
    const bottomRow: Box = { left: 12, top: 700, right: 378, bottom: 764 };
    const topBar: Box = { left: 12, top: 12, right: 378, bottom: 100 };
    const { container, el } = renderHud({
      docked: true,
      getChrome: () => ({ top: [topBar], side: [], bottom: [bottomRow] }),
    });
    runFrame();
    expect(container.querySelector("circle")).not.toBeNull();
    expect(container.querySelector("path.leader")).toBeNull();
    expect(el.style.bottom).toBe(`${844 - 688}px`);
    expect(el.style.maxHeight).toBe(`${688 - 112}px`);
    expect(el.style.left).toBe("");
    expect(el.dataset.placed).toBe("true");
  });

  it("stops its loop when the card goes", () => {
    const { rerender } = renderHud();
    runFrame();
    expect(frames.size).toBe(1);
    rerender(
      <GlobeHud
        point={null}
        project={() => ({ x: 0, y: 0 })}
        getGeometry={() => null}
        cardRef={{ current: null }}
        docked={false}
        reduced={false}
        getChrome={() => NO_CHROME}
      />,
    );
    expect(frames.size).toBe(0);
    expect(window.cancelAnimationFrame).toHaveBeenCalled();
  });

  it("stops its loop on unmount", () => {
    const { unmount } = renderHud();
    runFrame();
    unmount();
    expect(frames.size).toBe(0);
  });
});
