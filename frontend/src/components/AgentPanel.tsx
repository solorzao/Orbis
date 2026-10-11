"use client";

import { useRef, useEffect, useState, FormEvent } from "react";
import { motion, AnimatePresence } from "framer-motion";
import type { AgentMessage as AgentMessageType, Citation } from "@/hooks/useAgent";
import AgentMessage from "./AgentMessage";

const TOOL_LABELS: Record<string, string> = {
  semantic_search: "Searching articles",
  graph_traverse: "Traversing knowledge graph",
  keyword_search: "Keyword search",
  trending_topics: "Checking trends",
  entity_lookup: "Looking up entity",
  read_article: "Reading articles",
};

interface AgentPanelProps {
  messages: AgentMessageType[];
  isLoading: boolean;
  isDisabled?: boolean;
  activeTools: string[];
  onAsk: (question: string) => void;
  onStop: () => void;
  onClear: () => void;
  onCitationClick: (citation: Citation) => void;
}

/**
 * The agent chat, inside the side panel's Co-pilot tab: it fills the tab and
 * takes the panel's glass (PR 11 restyles it as the co-pilot console).
 */

export default function AgentPanel({
  messages,
  isLoading,
  isDisabled = false,
  activeTools,
  onAsk,
  onStop,
  onClear,
  onCitationClick,
}: AgentPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [input, setInput] = useState("");

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, activeTools]);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading || isDisabled) return;
    onAsk(input.trim());
    setInput("");
  };

  return (
    <div data-testid="agent-panel" className="flex min-h-0 flex-1 flex-col">
      {/* Toolbar: the side panel's tabs and collapse button replace the old header */}
      <div className="flex items-center gap-2 px-2 pb-2">
        <span className="h-1.5 w-1.5 rounded-full bg-[var(--signal-live)]" aria-hidden="true" />
        <p className="m-0 min-w-0 flex-1 truncate text-xs text-[var(--text-muted)]">
          Searches the news and moves the globe
        </p>
        <button
          type="button"
          onClick={onClear}
          className="iconbtn"
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
      </div>

      {/* Disabled banner */}
      {isDisabled && (
        <div className="mx-2 mb-2 rounded-2xl border border-[rgba(245,194,122,0.18)] bg-[rgba(245,194,122,0.08)] px-4 py-3 text-center text-xs leading-relaxed text-[var(--signal-warning)]">
          The agent is temporarily unavailable. Please try again later.
        </div>
      )}

      {/* Messages */}
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
        {messages.length === 0 && !isDisabled && (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
            <span className="text-4xl">🌍</span>
            <h3 className="text-sm font-medium text-[var(--text-primary)]">Ask about the news</h3>
            <p className="max-w-[260px] text-xs leading-relaxed text-[var(--text-muted)]">
              Ask questions about global events, trends, and stories. The agent will search articles
              and navigate the globe for you.
            </p>
          </div>
        )}

        <div className="space-y-3">
          {messages.map((msg) => (
            <AgentMessage key={msg.id} message={msg} onCitationClick={onCitationClick} />
          ))}
        </div>

        {/* Active tools */}
        <AnimatePresence>
          {activeTools.length > 0 && (
            <motion.div
              initial={{ opacity: 0, y: 5 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -5 }}
              className="mt-3 flex flex-wrap gap-1.5"
            >
              {activeTools.map((tool) => (
                <motion.span
                  key={tool}
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.9 }}
                  className="inline-flex items-center gap-1.5 rounded-full bg-[var(--accent-soft)] px-3 py-1 text-[11px] font-medium text-[var(--accent-strong)]"
                >
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--accent-strong)]" />
                  {TOOL_LABELS[tool] || tool}
                </motion.span>
              ))}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Input */}
      <div className="pt-2">
        <form onSubmit={handleSubmit} className="flex items-center gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            data-testid="agent-input"
            placeholder="Ask about global events..."
            disabled={isLoading || isDisabled}
            className="min-w-0 flex-1 rounded-full border border-[var(--border-subtle)] bg-[var(--bg-inset)] px-4 py-2.5 text-sm text-[var(--text-primary)] placeholder-[var(--text-muted)] transition-colors focus:border-[var(--border-edge-a)] disabled:opacity-50"
          />
          {isLoading ? (
            <button
              type="button"
              onClick={onStop}
              className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-[rgba(242,139,149,0.14)] text-[var(--signal-danger)] transition-colors hover:bg-[rgba(242,139,149,0.24)]"
              aria-label="Stop"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <rect x="3" y="3" width="8" height="8" rx="1" fill="currentColor" />
              </svg>
            </button>
          ) : (
            <button
              type="submit"
              disabled={!input.trim()}
              className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-[var(--accent-soft)] text-[var(--accent-strong)] transition-colors hover:bg-[rgba(0,212,255,0.24)] disabled:opacity-30"
              aria-label="Ask"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path
                  d="M1 7h10M8 4l3 3-3 3"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
          )}
        </form>
      </div>
    </div>
  );
}
