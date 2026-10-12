import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import CoPilot, { type ScreenContext } from "./CoPilot";
import type { AgentMessage, Citation, GlobeAction } from "@/hooks/useAgent";

const MADRID: ScreenContext = {
  place: "Madrid, Spain",
  topic: "Politics",
  window: {
    kind: "range",
    startTime: "2026-10-11T02:00:00.000Z",
    endTime: "2026-10-11T14:00:00.000Z",
  },
};
const NOWHERE: ScreenContext = { topic: "All", window: { kind: "live", hours: 24 } };

function renderCoPilot(overrides: Partial<Parameters<typeof CoPilot>[0]> = {}) {
  const props = {
    messages: [] as AgentMessage[],
    isLoading: false,
    activeTools: [] as string[],
    context: MADRID,
    onAsk: vi.fn(),
    onStop: vi.fn(),
    onClear: vi.fn(),
    onCitationClick: vi.fn(),
    onFlyTo: vi.fn(),
    ...overrides,
  };
  const view = render(<CoPilot {...props} />);
  return { props, ...props, ...view };
}

function ask(question: string) {
  const input = screen.getByTestId("agent-input");
  fireEvent.change(input, { target: { value: question } });
  fireEvent.submit(input.closest("form")!);
}

const lagos: Citation = {
  index: 1,
  title: "Floods hit Lagos",
  url: "https://example.com/lagos",
  source_name: "Reuters",
  lat: 6.45,
  lng: 3.39,
};
const accra: Citation = {
  index: 4,
  title: "Accra braces for rain",
  url: "https://example.com/accra",
  source_name: "BBC News",
  lat: 5.6,
  lng: -0.19,
};

function answer(overrides: Partial<AgentMessage> = {}): AgentMessage[] {
  return [
    { id: "q", role: "user", content: "What is happening in West Africa?" },
    {
      id: "a",
      role: "assistant",
      content: "Floods hit Lagos [1], and Accra is bracing [4].",
      citations: [lagos, accra],
      globeActions: [],
      status: "complete",
      ...overrides,
    },
  ];
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("CoPilot", () => {
  it("fills the Co-pilot tab: no overlay, no background, no close button of its own", () => {
    renderCoPilot();
    const panel = screen.getByTestId("agent-panel");
    expect(panel.className).not.toMatch(/\bfixed\b/);
    expect(panel.style.background).toBe("");
    expect(screen.queryByRole("button", { name: /Minimize/ })).toBeNull();
    expect(screen.getByText("Ask about the news")).toBeInTheDocument();
  });

  describe("context pills", () => {
    it("show what the co-pilot sees: the place, the topic and the window", () => {
      renderCoPilot();
      const ctx = screen.getByRole("group", { name: "What the co-pilot sees" });
      expect(ctx).toHaveTextContent(/^Sees/);
      expect(within(ctx).getByText("Madrid, Spain")).toBeInTheDocument();
      expect(within(ctx).getByText("Politics")).toBeInTheDocument();
      expect(within(ctx).getByText("Sun 02:00 – 14:00 UTC")).toBeInTheDocument();
    });

    it("leave out the topic on All and the place when none is open", () => {
      renderCoPilot({ context: NOWHERE });
      const ctx = screen.getByRole("group", { name: "What the co-pilot sees" });
      expect(within(ctx).getAllByRole("button")).toHaveLength(1);
      expect(within(ctx).getByText("Last 24 h, live")).toBeInTheDocument();
    });

    it("are sent with the question", () => {
      const { onAsk } = renderCoPilot();
      ask("  What is happening here?  ");
      expect(onAsk).toHaveBeenCalledWith("What is happening here?", {
        place: "Madrid, Spain",
        topic: "Politics",
        startTime: "2026-10-11T02:00:00.000Z",
        endTime: "2026-10-11T14:00:00.000Z",
      });
    });

    it("send a live window's bounds as of the question", () => {
      vi.useFakeTimers({ toFake: ["Date"] });
      vi.setSystemTime(new Date("2026-10-11T14:30:00.000Z"));
      const { onAsk } = renderCoPilot({ context: NOWHERE });
      ask("Anything new?");
      expect(onAsk).toHaveBeenCalledWith("Anything new?", {
        startTime: "2026-10-10T14:30:00.000Z",
        endTime: "2026-10-11T14:30:00.000Z",
      });
    });

    it("× leaves a field out of the next question only", () => {
      const { onAsk } = renderCoPilot();
      fireEvent.click(
        screen.getByRole("button", { name: "Remove Madrid, Spain from the context" }),
      );
      const ctx = screen.getByRole("group", { name: "What the co-pilot sees" });
      expect(within(ctx).queryByText("Madrid, Spain")).toBeNull();
      expect(screen.getByTestId("agent-input")).toHaveFocus(); // not lost with the button

      ask("What is happening?");
      expect(onAsk).toHaveBeenLastCalledWith("What is happening?", {
        topic: "Politics",
        startTime: "2026-10-11T02:00:00.000Z",
        endTime: "2026-10-11T14:00:00.000Z",
      });

      // back for the question after
      expect(within(ctx).getByText("Madrid, Spain")).toBeInTheDocument();
      ask("And now?");
      expect(onAsk).toHaveBeenLastCalledWith(
        "And now?",
        expect.objectContaining({ place: "Madrid, Spain" }),
      );
    });

    it("say so when everything is left out", () => {
      const { onAsk } = renderCoPilot({ context: NOWHERE });
      fireEvent.click(
        screen.getByRole("button", { name: "Remove Last 24 h, live from the context" }),
      );
      expect(screen.getByRole("group", { name: "What the co-pilot sees" })).toHaveTextContent(
        "Sees the whole globe",
      );
      ask("Anything?");
      expect(onAsk).toHaveBeenCalledWith("Anything?", {});
    });

    it("a new place is not left out by an earlier ×", () => {
      const { props, rerender } = renderCoPilot();
      fireEvent.click(
        screen.getByRole("button", { name: "Remove Madrid, Spain from the context" }),
      );
      rerender(<CoPilot {...props} context={{ ...MADRID, place: "Lisbon, Portugal" }} />);
      expect(screen.getByText("Lisbon, Portugal")).toBeInTheDocument();
    });
  });

  describe("quick prompts", () => {
    const prompts = () =>
      within(screen.getByRole("group", { name: "Suggested questions" }))
        .getAllByRole("button")
        .map((b) => b.textContent);

    it("brief on the place when one is open", () => {
      renderCoPilot();
      expect(prompts()).toEqual([
        "Brief me on Madrid, Spain",
        "What's driving coverage in Madrid, Spain?",
      ]);
    });

    it("ask about the topic when only a topic is set", () => {
      renderCoPilot({ context: { ...MADRID, place: undefined } });
      expect(prompts()).toEqual(["What's happening in Politics today?"]);
    });

    it("ask for the biggest story with neither", () => {
      renderCoPilot({ context: NOWHERE });
      expect(prompts()).toEqual(["What's the biggest story right now?"]);
    });

    it("follow the pills that are left", () => {
      renderCoPilot();
      fireEvent.click(
        screen.getByRole("button", { name: "Remove Madrid, Spain from the context" }),
      );
      expect(prompts()).toEqual(["What's happening in Politics today?"]);
    });

    it("ask the question with the context", () => {
      const { onAsk } = renderCoPilot();
      fireEvent.click(screen.getByRole("button", { name: "Brief me on Madrid, Spain" }));
      expect(onAsk).toHaveBeenCalledWith(
        "Brief me on Madrid, Spain",
        expect.objectContaining({ place: "Madrid, Spain", topic: "Politics" }),
      );
    });

    it("wait while an answer streams", () => {
      renderCoPilot({ isLoading: true });
      expect(screen.getByRole("button", { name: "Brief me on Madrid, Spain" })).toBeDisabled();
    });
  });

  describe("messages", () => {
    it("show the question as a bubble and the answer as prose", () => {
      const { container } = renderCoPilot({ messages: answer() });
      expect(container.querySelector(".msg.user")).toHaveTextContent(
        "What is happening in West Africa?",
      );
      expect(container.querySelector(".msg.bot p")).toHaveTextContent(/^Floods hit Lagos/);
    });

    it("turn citation markers into pills that open their source", () => {
      const { onCitationClick } = renderCoPilot({ messages: answer() });
      const prose = document.querySelector(".msg.bot p")!;
      const four = within(prose as HTMLElement).getByRole("button", { name: "Source 4" });
      expect(four).toHaveClass("cite");
      expect(four).toHaveTextContent("4");
      expect(four).toHaveAttribute("title", "BBC News: Accra braces for rain");
      fireEvent.click(four);
      expect(onCitationClick).toHaveBeenCalledWith(accra);
    });

    it("number citations by position when they have no index", () => {
      const { onCitationClick } = renderCoPilot({
        messages: answer({
          content: "Floods [1] and rain [2].",
          citations: [
            { ...lagos, index: undefined },
            { ...accra, index: undefined },
          ],
        }),
      });
      fireEvent.click(screen.getAllByRole("button", { name: "Source 2" })[0]);
      expect(onCitationClick).toHaveBeenCalledWith(expect.objectContaining({ title: accra.title }));
    });

    it("leave a marker with no source as a plain pill", () => {
      renderCoPilot({ messages: answer({ content: "Floods [7]." }) });
      const prose = document.querySelector(".msg.bot p") as HTMLElement;
      expect(within(prose).queryByRole("button")).toBeNull();
      expect(prose.querySelector(".cite")).toHaveTextContent("7");
    });

    it("list the sources after the answer", () => {
      const { onCitationClick } = renderCoPilot({ messages: answer() });
      const sources = screen.getByRole("group", { name: "Sources" });
      const rows = within(sources).getAllByRole("button");
      expect(rows.map((r) => r.textContent)).toEqual([
        "1Reuters: Floods hit Lagos",
        "4BBC News: Accra braces for rain",
      ]);
      fireEvent.click(rows[1]);
      expect(onCitationClick).toHaveBeenCalledWith(accra);
    });

    it("show one quiet tool line while the answer streams", () => {
      renderCoPilot({
        isLoading: true,
        activeTools: ["semantic_search", "trending_topics"],
        messages: answer({ content: "", citations: [], status: "streaming" }),
      });
      expect(screen.getByText("Searching articles, checking trends…")).toBeInTheDocument();
    });

    it("never load an image the answer writes", () => {
      const { container } = renderCoPilot({
        messages: answer({ content: "Floods [1]. ![x](https://evil.example/pixel.png)" }),
      });
      expect(container.querySelector("img")).toBeNull();
      expect(container.querySelector(".msg.bot p")).toHaveTextContent(/^Floods/);
    });

    it("open links in the answer in a new tab", () => {
      renderCoPilot({
        messages: answer({ content: "See [the report](https://example.com/report)." }),
      });
      const link = screen.getByRole("link", { name: "the report" });
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
    });
  });

  describe("action pills", () => {
    const actions: GlobeAction[] = [
      { type: "flyTo", lat: 6.45, lng: 3.39, label: `${String.fromCharCode(0x202e)}Lagos` },
      { type: "flyTo", lat: 5.6, lng: -0.19, label: "" },
    ];

    it("fly to each place the answer names, by its cleaned label", () => {
      const { onFlyTo } = renderCoPilot({ messages: answer({ globeActions: actions }) });
      const group = screen.getByRole("group", { name: "Suggested actions" });
      const pills = within(group).getAllByRole("button");
      expect(pills.map((p) => p.textContent)).toEqual(["Fly to Lagos", "Fly there"]);
      fireEvent.click(pills[0]);
      expect(onFlyTo).toHaveBeenCalledWith(actions[0]);
    });

    it("show the stories at the first place when the globe has a dot there", () => {
      const open = vi.fn();
      const showStoriesFor = vi.fn(() => open);
      renderCoPilot({ messages: answer({ globeActions: actions }), showStoriesFor });
      fireEvent.click(screen.getByRole("button", { name: "Show stories here" }));
      expect(showStoriesFor).toHaveBeenCalledWith(actions[0]);
      expect(open).toHaveBeenCalled();
    });

    it("hide Show stories here when there is no dot", () => {
      renderCoPilot({ messages: answer({ globeActions: actions }), showStoriesFor: () => null });
      expect(screen.queryByRole("button", { name: "Show stories here" })).toBeNull();
    });

    it("are not looked up again while the next answer streams", () => {
      const showStoriesFor = vi.fn(() => null);
      const done = answer({ globeActions: actions });
      const asking = (content: string): AgentMessage[] => [
        ...done,
        { id: "q2", role: "user", content: "And Ghana?" },
        { id: "a2", role: "assistant", content, status: "streaming" },
      ];
      const { props, rerender } = renderCoPilot({
        messages: asking(""),
        showStoriesFor,
        isLoading: true,
      });
      expect(showStoriesFor).toHaveBeenCalledTimes(1);

      rerender(<CoPilot {...props} messages={asking("Gh")} />);
      rerender(<CoPilot {...props} messages={asking("Ghana's")} />);
      expect(screen.getByText("Ghana's")).toBeInTheDocument();
      expect(showStoriesFor).toHaveBeenCalledTimes(1);
    });

    it("offer Show links when the answer's places span countries and Links is off", () => {
      const turnOn = vi.fn();
      const showLinksFor = vi.fn(() => turnOn);
      renderCoPilot({ messages: answer({ globeActions: actions }), showLinksFor });
      expect(showLinksFor).toHaveBeenCalledWith(actions);
      const pills = within(screen.getByRole("group", { name: "Suggested actions" })).getAllByRole(
        "button",
      );
      expect(pills.map((p) => p.textContent)).toEqual(["Fly to Lagos", "Fly there", "Show links"]);
      fireEvent.click(pills[2]);
      expect(turnOn).toHaveBeenCalled();
    });

    it("leave out Show links when it does not apply", () => {
      renderCoPilot({ messages: answer({ globeActions: actions }), showLinksFor: () => null });
      expect(screen.queryByRole("button", { name: "Show links" })).toBeNull();
    });

    it("wait for the answer to finish", () => {
      renderCoPilot({ messages: answer({ globeActions: actions, status: "streaming" }) });
      expect(screen.queryByRole("group", { name: "Suggested actions" })).toBeNull();
    });
  });

  describe("auto-scroll", () => {
    /** The log's box, as a browser lays it out; a hidden (display: none) log has none. */
    function layOut(log: HTMLElement) {
      const box = { clientHeight: 200, scrollHeight: 1000, top: 0 };
      Object.defineProperties(log, {
        clientHeight: { configurable: true, get: () => box.clientHeight },
        scrollHeight: { configurable: true, get: () => box.scrollHeight },
        scrollTop: {
          configurable: true,
          get: () => box.top,
          set: (v: number) => {
            if (box.clientHeight === 0) return;
            box.top = Math.max(0, Math.min(v, box.scrollHeight - box.clientHeight));
          },
        },
      });
      return box;
    }

    let resized = () => {};
    function stubResizeObserver() {
      vi.stubGlobal(
        "ResizeObserver",
        class {
          constructor(callback: () => void) {
            resized = () => callback();
          }
          observe() {}
          disconnect() {}
        },
      );
    }

    function longer(by: string): AgentMessage[] {
      const [q, a] = answer();
      return [q, { ...a, content: `${a.content} ${by}` }];
    }

    it("follows the latest message", () => {
      stubResizeObserver();
      const { props, rerender } = renderCoPilot({ messages: answer() });
      const box = layOut(screen.getByTestId("agent-log"));
      resized();
      expect(box.top).toBe(800);

      box.scrollHeight = 1300;
      rerender(<CoPilot {...props} messages={longer("More.")} />);
      expect(box.top).toBe(1100);
    });

    it("shows an answer that landed while the tab was hidden when it is shown again", () => {
      stubResizeObserver();
      const { props, rerender } = renderCoPilot({ messages: answer() });
      const box = layOut(screen.getByTestId("agent-log"));
      resized();

      box.clientHeight = 0; // Inspect tab: the log is display: none
      resized();
      box.scrollHeight = 1600;
      rerender(<CoPilot {...props} messages={longer("A long answer.")} />);
      expect(box.top).toBe(800); // nothing to scroll while hidden

      box.clientHeight = 200; // back on Co-pilot
      resized();
      expect(box.top).toBe(1400);
    });

    it("keeps the reader's place when they had scrolled back", () => {
      stubResizeObserver();
      const { props, rerender } = renderCoPilot({ messages: answer() });
      const log = screen.getByTestId("agent-log");
      const box = layOut(log);
      resized();

      box.top = 300;
      fireEvent.scroll(log);
      expect(log).toHaveClass("scrolled"); // the top edge fades
      box.scrollHeight = 1100;
      rerender(<CoPilot {...props} messages={longer("More.")} />);
      expect(box.top).toBe(300);

      box.clientHeight = 0;
      box.top = 0; // some browsers drop the offset with the box
      resized();
      box.clientHeight = 200;
      resized();
      expect(box.top).toBe(300);
    });

    it("goes back to the latest message when the visitor asks", () => {
      stubResizeObserver();
      const { props, rerender } = renderCoPilot({ messages: answer() });
      const log = screen.getByTestId("agent-log");
      const box = layOut(log);
      resized();
      box.top = 100;
      fireEvent.scroll(log);

      ask("And Ghana?");
      box.scrollHeight = 1200;
      rerender(<CoPilot {...props} messages={longer("Ghana.")} />);
      expect(box.top).toBe(1000);
    });
  });

  describe("composer", () => {
    it("asks the question and empties the input", () => {
      const { onAsk } = renderCoPilot();
      const input = screen.getByTestId("agent-input");
      expect(input).toHaveAttribute("placeholder", "Ask about what you see");
      expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();

      fireEvent.change(input, { target: { value: "  What is happening in France?  " } });
      expect(screen.getByRole("button", { name: "Ask" })).toBeEnabled();
      fireEvent.submit(input.closest("form")!);
      expect(onAsk).toHaveBeenCalledWith("What is happening in France?", expect.any(Object));
      expect(input).toHaveValue("");
    });

    it("keeps the send button disabled for a blank question", () => {
      const { onAsk } = renderCoPilot();
      fireEvent.change(screen.getByTestId("agent-input"), { target: { value: "   " } });
      expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
      fireEvent.submit(screen.getByTestId("agent-input").closest("form")!);
      expect(onAsk).not.toHaveBeenCalled();
    });

    it("clears the conversation", () => {
      const { onClear } = renderCoPilot({ messages: answer() });
      fireEvent.click(screen.getByRole("button", { name: "Clear conversation" }));
      expect(onClear).toHaveBeenCalled();
    });

    it("offers Stop while answering", () => {
      const { onStop } = renderCoPilot({ isLoading: true });
      fireEvent.click(screen.getByRole("button", { name: "Stop" }));
      expect(onStop).toHaveBeenCalled();
    });

    it("says when the agent is unavailable", () => {
      renderCoPilot({ isDisabled: true });
      expect(screen.getByText(/temporarily unavailable/)).toBeInTheDocument();
      expect(screen.getByTestId("agent-input")).toBeDisabled();
    });
  });
});
