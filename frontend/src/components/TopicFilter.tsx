"use client";

import { useRef, useState, useEffect, useCallback } from "react";
import { motion } from "framer-motion";
import { Topic } from "@/types/news";
import { getTopicColor } from "@/lib/clustering";

const TOPICS: Topic[] = [
  "All",
  "Politics",
  "Conflict",
  "Technology",
  "Climate",
  "Economy",
  "Health",
];

interface TopicFilterProps {
  activeTopic: Topic;
  onTopicChange: (topic: Topic) => void;
}

export default function TopicFilter({ activeTopic, onTopicChange }: TopicFilterProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);

  const checkScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    setCanScrollLeft(el.scrollLeft > 2);
    setCanScrollRight(el.scrollLeft < el.scrollWidth - el.clientWidth - 2);
  }, []);

  useEffect(() => {
    checkScroll();
    window.addEventListener("resize", checkScroll);
    return () => window.removeEventListener("resize", checkScroll);
  }, [checkScroll]);

  return (
    <div className="fixed top-12 left-1/2 z-40 max-w-[calc(100vw-1.5rem)] -translate-x-1/2 sm:top-6">
      {/* Left fade */}
      {canScrollLeft && (
        <div
          className="pointer-events-none absolute top-0 left-0 z-10 h-full w-6 rounded-l-2xl"
          style={{ background: "linear-gradient(to right, var(--bg-page), transparent)" }}
        />
      )}
      {/* Right fade */}
      {canScrollRight && (
        <div
          className="pointer-events-none absolute top-0 right-0 z-10 h-full w-6 rounded-r-2xl"
          style={{ background: "linear-gradient(to left, var(--bg-page), transparent)" }}
        />
      )}
      <motion.div
        ref={scrollRef}
        onScroll={checkScroll}
        initial={{ y: -30, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ delay: 0.5, duration: 0.6, ease: [0.23, 1, 0.32, 1] }}
        className="flex items-center gap-0.5 overflow-x-auto rounded-2xl border border-[var(--border-subtle)] px-1.5 py-1 sm:gap-1 sm:px-2 sm:py-1.5"
        style={{
          background: "var(--surface-overlay)",
          backdropFilter: "blur(20px) saturate(1.3)",
          boxShadow: "0 8px 32px var(--shadow), inset 0 1px 0 var(--inset-highlight)",
          scrollbarWidth: "none",
        }}
      >
        {TOPICS.map((topic) => {
          const isActive = activeTopic === topic;
          const color = getTopicColor(topic);

          return (
            <button
              key={topic}
              onClick={() => onTopicChange(topic)}
              className="relative shrink-0 rounded-xl px-2.5 py-1 text-[11px] font-medium tracking-wide transition-colors sm:px-3.5 sm:py-1.5 sm:text-xs"
              style={{
                color: isActive ? "#fff" : "var(--text-muted)",
              }}
            >
              {isActive && (
                <motion.div
                  layoutId="activeFilter"
                  className="absolute inset-0 rounded-xl"
                  style={{
                    background: `${color}18`,
                    border: `1px solid ${color}30`,
                    boxShadow: `0 0 20px ${color}15`,
                  }}
                  transition={{
                    type: "spring",
                    stiffness: 400,
                    damping: 30,
                  }}
                />
              )}
              <span className="relative z-10 flex items-center gap-1.5">
                {topic !== "All" && (
                  <span
                    className="inline-block h-1.5 w-1.5 rounded-full"
                    style={{
                      backgroundColor: isActive ? color : "var(--text-muted)",
                      boxShadow: isActive ? `0 0 6px ${color}60` : "none",
                    }}
                  />
                )}
                {topic}
              </span>
            </button>
          );
        })}
      </motion.div>
    </div>
  );
}
