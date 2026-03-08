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
};

interface AgentPanelProps {
  messages: AgentMessageType[];
  isLoading: boolean;
  activeTools: string[];
  onAsk: (question: string) => void;
  onStop: () => void;
  onClear: () => void;
  onCitationClick: (citation: Citation) => void;
  onClose: () => void;
}

export default function AgentPanel({
  messages,
  isLoading,
  activeTools,
  onAsk,
  onStop,
  onClear,
  onCitationClick,
  onClose,
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
    if (!input.trim() || isLoading) return;
    onAsk(input.trim());
    setInput("");
  };

  return (
    <motion.div
      initial={{ x: "-100%" }}
      animate={{ x: 0 }}
      exit={{ x: "-100%" }}
      transition={{ type: "spring", damping: 28, stiffness: 300 }}
      className="fixed left-0 top-0 z-50 flex h-full w-full max-w-md flex-col border-r border-[var(--border-subtle)]"
      style={{
        background: "var(--surface-panel)",
        backdropFilter: "blur(24px) saturate(1.4)",
      }}
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--border-subtle)] px-6 py-4">
        <div className="flex items-center gap-2.5">
          <span className="relative flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-400 opacity-75" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-blue-500" />
          </span>
          <h2
            className="text-sm font-semibold tracking-widest text-blue-400 uppercase"
            style={{ fontFamily: "var(--font-heading), sans-serif" }}
          >
            Orbis Agent
          </h2>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={onClear}
            className="group flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--border-subtle)] text-[var(--text-muted)] transition-colors hover:border-blue-500/30 hover:text-[var(--text-secondary)]"
            aria-label="Clear conversation"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path
                d="M2 4h10M5 4V3a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v1M6 7v3M8 7v3M3 4l.5 7a2 2 0 0 0 2 2h3a2 2 0 0 0 2-2L11 4"
                stroke="currentColor"
                strokeWidth="1.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
          <button
            onClick={onClose}
            className="group flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--border-subtle)] text-[var(--text-muted)] transition-colors hover:border-blue-500/30 hover:text-[var(--text-secondary)]"
            aria-label="Close panel"
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 14 14"
              fill="none"
              className="transition-transform group-hover:scale-110"
            >
              <path
                d="M1 1L13 13M13 1L1 13"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4">
        {messages.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
            <span className="text-4xl">🌍</span>
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">
              Ask about the news
            </h3>
            <p className="max-w-[260px] text-xs leading-relaxed text-[var(--text-muted)]">
              Ask questions about global events, trends, and stories. The agent
              will search articles and navigate the globe for you.
            </p>
          </div>
        )}

        <div className="space-y-3">
          {messages.map((msg) => (
            <AgentMessage
              key={msg.id}
              message={msg}
              onCitationClick={onCitationClick}
            />
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
                  className="inline-flex items-center gap-1.5 rounded-full bg-blue-500/10 px-3 py-1 text-[11px] font-medium text-blue-400"
                >
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-400" />
                  {TOOL_LABELS[tool] || tool}
                </motion.span>
              ))}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Input */}
      <div className="border-t border-[var(--border-subtle)] px-4 py-3">
        <form onSubmit={handleSubmit} className="flex items-center gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about global events..."
            disabled={isLoading}
            className="flex-1 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-overlay)] px-3.5 py-2.5 text-sm text-[var(--text-primary)] placeholder-[var(--text-muted)] outline-none transition-colors focus:border-blue-500/40 disabled:opacity-50"
          />
          {isLoading ? (
            <button
              type="button"
              onClick={onStop}
              className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg bg-red-500/20 text-red-400 transition-colors hover:bg-red-500/30"
              aria-label="Stop"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <rect
                  x="3"
                  y="3"
                  width="8"
                  height="8"
                  rx="1"
                  fill="currentColor"
                />
              </svg>
            </button>
          ) : (
            <button
              type="submit"
              disabled={!input.trim()}
              className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg bg-blue-500/20 text-blue-400 transition-colors hover:bg-blue-500/30 disabled:opacity-30"
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
    </motion.div>
  );
}
