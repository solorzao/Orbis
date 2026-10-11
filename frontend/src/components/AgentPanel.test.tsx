import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import AgentPanel from "./AgentPanel";

function renderPanel(overrides: Partial<Parameters<typeof AgentPanel>[0]> = {}) {
  const props = {
    messages: [],
    isLoading: false,
    activeTools: [],
    onAsk: vi.fn(),
    onStop: vi.fn(),
    onClear: vi.fn(),
    onCitationClick: vi.fn(),
    ...overrides,
  };
  render(<AgentPanel {...props} />);
  return props;
}

describe("AgentPanel", () => {
  it("fills the Co-pilot tab: no overlay, no background, no close button of its own", () => {
    renderPanel();
    const panel = screen.getByTestId("agent-panel");
    expect(panel.className).not.toMatch(/\bfixed\b/);
    expect(panel.style.background).toBe("");
    expect(screen.queryByRole("button", { name: /Minimize/ })).toBeNull();
    expect(screen.getByText("Ask about the news")).toBeInTheDocument();
  });

  it("asks the question and empties the input", () => {
    const { onAsk } = renderPanel();
    const input = screen.getByTestId("agent-input");
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();

    fireEvent.change(input, { target: { value: "  What is happening in France?  " } });
    fireEvent.submit(input.closest("form")!);
    expect(onAsk).toHaveBeenCalledWith("What is happening in France?");
    expect(input).toHaveValue("");
  });

  it("clears the conversation", () => {
    const { onClear } = renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "Clear conversation" }));
    expect(onClear).toHaveBeenCalled();
  });

  it("offers Stop while answering", () => {
    const { onStop } = renderPanel({ isLoading: true });
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(onStop).toHaveBeenCalled();
  });

  it("says when the agent is unavailable", () => {
    renderPanel({ isDisabled: true });
    expect(screen.getByText(/temporarily unavailable/)).toBeInTheDocument();
    expect(screen.getByTestId("agent-input")).toBeDisabled();
  });
});
