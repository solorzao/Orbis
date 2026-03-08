"use client";

import { motion } from "framer-motion";
import type { AgentMessage as AgentMessageType, Citation } from "@/hooks/useAgent";

interface AgentMessageProps {
  message: AgentMessageType;
  onCitationClick?: (citation: Citation) => void;
}

export default function AgentMessage({ message, onCitationClick }: AgentMessageProps) {
  const isUser = message.role === "user";

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: [0.23, 1, 0.32, 1] }}
      className={`flex ${isUser ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`max-w-[85%] rounded-xl px-4 py-3 ${
          isUser
            ? "bg-blue-500/20 text-[var(--text-primary)]"
            : "border border-[var(--border-subtle)] bg-[var(--surface-card)] text-[var(--text-secondary)]"
        }`}
      >
        <p className="whitespace-pre-wrap text-sm leading-relaxed">
          {message.content}
          {message.status === "streaming" && (
            <svg className="ml-1 inline-block h-4 w-4 animate-spin text-blue-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><circle cx="12" cy="12" r="10" strokeOpacity="0.25" /><path d="M12 2a10 10 0 0 1 10 10" strokeLinecap="round" /></svg>
          )}
        </p>

        {/* Citations */}
        {message.citations && message.citations.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {message.citations.map((citation, i) => (
              <button
                key={`${citation.url}-${i}`}
                onClick={() => onCitationClick?.(citation)}
                className="inline-flex min-w-0 max-w-full items-center gap-1 rounded-full bg-blue-500/10 px-2.5 py-1 text-[11px] text-blue-400 transition-colors hover:bg-blue-500/20"
              >
                <span className="font-semibold">[{i + 1}]</span>
                <span className="max-w-[180px] truncate">
                  {citation.title}
                </span>
                <span className="text-[var(--text-muted)]">&mdash;</span>
                <span className="max-w-[100px] truncate text-[var(--text-muted)]">
                  {citation.source_name}
                </span>
                <svg className="h-2.5 w-2.5 opacity-50" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M4.5 1.5H2a.5.5 0 0 0-.5.5v8a.5.5 0 0 0 .5.5h8a.5.5 0 0 0 .5-.5V7.5M7 1.5h3.5V5M6 6l4.5-4.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
              </button>
            ))}
          </div>
        )}
      </div>
    </motion.div>
  );
}
