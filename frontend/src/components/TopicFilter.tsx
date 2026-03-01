"use client";

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
  return (
    <div className="fixed top-12 left-1/2 z-40 max-w-[calc(100vw-1.5rem)] -translate-x-1/2 sm:top-6">
      <motion.div
        initial={{ y: -30, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ delay: 0.5, duration: 0.6, ease: [0.23, 1, 0.32, 1] }}
        className="flex items-center gap-0.5 overflow-x-auto rounded-2xl border border-white/[0.06] px-1.5 py-1 sm:gap-1 sm:px-2 sm:py-1.5"
        style={{
          background: "rgba(8, 12, 24, 0.65)",
          backdropFilter: "blur(20px) saturate(1.3)",
          boxShadow: "0 8px 32px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255,255,255,0.03)",
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
                color: isActive ? "#fff" : "#64748b",
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
                      backgroundColor: isActive ? color : "#334155",
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
