"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import {
  cleanLabel,
  type AgentMessage as AgentMessageType,
  type AskContext,
  type Citation,
  type GlobeAction,
} from "@/hooks/useAgent";
import { windowBounds, windowLabel, type TimeWindow } from "@/lib/timeWindow";
import type { Topic } from "@/types/news";
import AgentMessage from "./AgentMessage";

/** Within this of the bottom, the log follows new messages. */
const FOLLOW_SLACK_PX = 24;

/** What the visitor sees, live: the co-pilot's context pills read it. */
export interface ScreenContext {
  /** The place open in the Inspect tab, e.g. "Madrid, Spain". */
  place?: string;
  topic: Topic;
  window: TimeWindow;
}

type Field = "place" | "topic" | "window";

interface ContextPill {
  field: Field;
  label: string;
}

/** The pills, in the mockup's order: the place, the topic (unless All), the window. */
function contextPills({ place, topic, window }: ScreenContext): ContextPill[] {
  const pills: ContextPill[] = [];
  const name = cleanLabel(place, 100);
  if (name) pills.push({ field: "place", label: name });
  if (topic !== "All") pills.push({ field: "topic", label: topic });
  pills.push({ field: "window", label: windowLabel(window) });
  return pills;
}

/** Quick prompts that follow what the co-pilot sees. */
function quickPrompts(place?: string, topic?: string): string[] {
  if (place) return [`Brief me on ${place}`, `What's driving coverage in ${place}?`];
  if (topic) return [`What's happening in ${topic} today?`];
  return ["What's the biggest story right now?"];
}

/** What a question is sent with: the pills left in, a window as its bounds right now. */
function askContext(place?: string, topic?: Topic, window?: TimeWindow): AskContext {
  const asked: AskContext = {};
  if (place) asked.place = place;
  if (topic && topic !== "All") asked.topic = topic;
  if (window) Object.assign(asked, windowBounds(window, Date.now()));
  return asked;
}

interface CoPilotProps {
  messages: AgentMessageType[];
  isLoading: boolean;
  isDisabled?: boolean;
  activeTools: string[];
  context: ScreenContext;
  /** Ask a question with the context pills left in (the window's bounds as of now). */
  onAsk: (question: string, context: AskContext) => void;
  onStop: () => void;
  onClear: () => void;
  onCitationClick: (citation: Citation) => void;
  onFlyTo: (action: GlobeAction) => void;
  /** Opens the Inspect tab at an action's place, or null when the globe has no dot there. */
  showStoriesFor?: (action: GlobeAction) => (() => void) | null;
  /** Turns the Links layer on for an answer's places, or null when that does not apply. */
  showLinksFor?: (actions: GlobeAction[]) => (() => void) | null;
}

/**
 * The co-pilot console in the side panel's Co-pilot tab (mockup .side, lines
 * 332-356, and copilotHTML): what it sees as pills, the conversation, quick
 * prompts and the composer.
 */
export default function CoPilot({
  messages,
  isLoading,
  isDisabled = false,
  activeTools,
  context,
  onAsk,
  onStop,
  onClear,
  onCitationClick,
  onFlyTo,
  showStoriesFor,
  showLinksFor,
}: CoPilotProps) {
  const [input, setInput] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  // Pills left out of the next question, by field and the label they had: a
  // new place or window is in again.
  const [removed, setRemoved] = useState<Partial<Record<Field, string>>>({});
  const logRef = useRef<HTMLDivElement>(null);
  // Whether the log follows the latest message (the visitor has not scrolled
  // back), and where it was when it last had a box.
  const following = useRef(true);
  const lastTop = useRef(0);

  /** Scroll to the latest message, or back to the visitor's place. */
  const settle = useCallback(() => {
    const log = logRef.current;
    if (!log || log.clientHeight === 0) return; // hidden (another tab, a folded sheet): no box
    log.scrollTop = following.current ? log.scrollHeight : lastTop.current;
  }, []);

  const onScroll = () => {
    const log = logRef.current;
    if (!log || log.clientHeight === 0) return;
    following.current = log.scrollHeight - log.scrollTop - log.clientHeight <= FOLLOW_SLACK_PX;
    lastTop.current = log.scrollTop;
    log.classList.toggle("scrolled", log.scrollTop > 4);
  };

  // New messages, tokens and tool lines.
  useEffect(() => {
    if (following.current) settle();
  }, [messages, activeTools, settle]);

  // Shown again, or resized: what landed while the tab was hidden comes into
  // view, and a hidden log's lost offset comes back.
  useEffect(() => {
    const log = logRef.current;
    if (!log || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(settle);
    observer.observe(log);
    return () => observer.disconnect();
  }, [settle]);

  const pills = contextPills(context).filter((p) => removed[p.field] !== p.label);
  const sees = (field: Field) => pills.some((p) => p.field === field);
  const place = sees("place") ? cleanLabel(context.place, 100) : undefined;
  const topic = sees("topic") && context.topic !== "All" ? context.topic : undefined;
  const busy = isLoading || isDisabled;

  const remove = (pill: ContextPill) => {
    setRemoved((prev) => ({ ...prev, [pill.field]: pill.label }));
    inputRef.current?.focus(); // the × goes with its pill
  };

  const ask = (question: string) => {
    const q = question.trim();
    if (!q || busy) return;
    following.current = true; // the answer comes into view
    onAsk(q, askContext(place, topic, sees("window") ? context.window : undefined));
    setRemoved({}); // for the next question only
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!input.trim() || busy) return;
    ask(input);
    setInput("");
  };

  return (
    <div data-testid="agent-panel" className="copilot">
      <div className="ctx" role="group" aria-label="What the co-pilot sees">
        <span>{pills.length > 0 ? "Sees" : "Sees the whole globe"}</span>
        {pills.map((pill) => (
          <span key={pill.field} className="pill">
            <span className="ctx-label" title={pill.label}>
              {pill.label}
            </span>
            <button
              type="button"
              className="ctx-x"
              aria-label={`Remove ${pill.label} from the context`}
              title="Leave out of the next question"
              onClick={() => remove(pill)}
            >
              <svg
                width="8"
                height="8"
                viewBox="0 0 10 10"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                aria-hidden="true"
              >
                <path d="M2 2l6 6M8 2l-6 6" />
              </svg>
            </button>
          </span>
        ))}
      </div>

      {isDisabled && (
        <p className="callout" role="status">
          The agent is temporarily unavailable. Please try again later.
        </p>
      )}

      <div ref={logRef} className="cp-log" data-testid="agent-log" onScroll={onScroll}>
        {messages.length === 0 && !isDisabled && (
          <div className="cp-empty">
            <h3>Ask about the news</h3>
            <p>It searches the stories on the globe, cites them and flies you to the places.</p>
          </div>
        )}
        {messages.map((msg) => (
          <AgentMessage
            key={msg.id}
            message={msg}
            activeTools={msg.status === "streaming" ? activeTools : undefined}
            onCitationClick={onCitationClick}
            onFlyTo={onFlyTo}
            showStoriesFor={showStoriesFor}
            showLinksFor={showLinksFor}
          />
        ))}
      </div>

      <div className="quick" role="group" aria-label="Suggested questions">
        {quickPrompts(place, topic).map((prompt) => (
          <button
            key={prompt}
            type="button"
            className="pill"
            disabled={busy}
            onClick={() => ask(prompt)}
          >
            {prompt}
          </button>
        ))}
      </div>

      <form className="composer" onSubmit={handleSubmit}>
        {messages.length > 0 && (
          <button
            type="button"
            className="iconbtn"
            onClick={onClear}
            aria-label="Clear conversation"
            title="Clear conversation"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
              <path
                d="M2 4h10M5 4V3a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v1M6 7v3M8 7v3M3 4l.5 7a2 2 0 0 0 2 2h3a2 2 0 0 0 2-2L11 4"
                stroke="currentColor"
                strokeWidth="1.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        )}
        <label>
          <span className="sr-only">Ask the co-pilot</span>
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            data-testid="agent-input"
            placeholder="Ask about what you see"
            disabled={busy}
          />
        </label>
        {isLoading ? (
          <button
            type="button"
            className="iconbtn stop"
            onClick={onStop}
            aria-label="Stop"
            title="Stop"
          >
            <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
              <rect x="2" y="2" width="8" height="8" rx="1.5" fill="currentColor" />
            </svg>
          </button>
        ) : (
          <button
            type="submit"
            className="aurora-btn"
            disabled={!input.trim() || isDisabled}
            aria-label="Ask"
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 12 12"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M2 6h8M7 3l3 3-3 3" />
            </svg>
          </button>
        )}
      </form>
    </div>
  );
}
