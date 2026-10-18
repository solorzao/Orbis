"use client";

import { useRef, useState, useEffect, useCallback, type CSSProperties, type Ref } from "react";
import { Topic } from "@/types/news";

const TOPICS: Topic[] = [
  "All",
  "Politics",
  "Conflict",
  "Technology",
  "Climate",
  "Economy",
  "Health",
];

type Fade = "none" | "left" | "right" | "both";

interface TopicFilterProps {
  activeTopic: Topic;
  onTopicChange: (topic: Topic) => void;
  /** The pills' nav, where focus can land when a control near it goes. */
  navRef?: Ref<HTMLElement>;
}

/**
 * Topic pills in the top bar's centre track. When the track is narrower than
 * the pills, they scroll inside the glass and fade at the clipped edge.
 */
export default function TopicFilter({ activeTopic, onTopicChange, navRef }: TopicFilterProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [fade, setFade] = useState<Fade>("none");

  const checkScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const left = el.scrollLeft > 2;
    const right = el.scrollLeft < el.scrollWidth - el.clientWidth - 2;
    setFade(left && right ? "both" : left ? "left" : right ? "right" : "none");
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    // Fires once on observe, then whenever the track resizes (viewport) or a
    // pill does (the self-hosted font arriving).
    const ro = new ResizeObserver(checkScroll);
    ro.observe(el);
    for (const pill of Array.from(el.children)) ro.observe(pill);
    return () => ro.disconnect();
  }, [checkScroll]);

  return (
    <nav
      ref={navRef}
      className="pillbar topics"
      aria-label="Topic filter"
      data-testid="topic-filter"
    >
      <div ref={scrollRef} className="topics-scroll" data-fade={fade} onScroll={checkScroll}>
        {TOPICS.map((topic) => (
          <button
            key={topic}
            type="button"
            className="pill"
            aria-pressed={activeTopic === topic}
            onClick={() => onTopicChange(topic)}
          >
            {topic !== "All" && (
              <span
                className="dot"
                aria-hidden="true"
                style={{ "--c": `var(--topic-${topic.toLowerCase()})` } as CSSProperties}
              />
            )}
            {topic}
          </button>
        ))}
      </div>
    </nav>
  );
}
