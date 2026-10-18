"use client";

import type { Ref } from "react";
import Link from "next/link";
import { Topic } from "@/types/news";
import TopicFilter from "@/components/TopicFilter";
import StatusPill from "@/components/StatusPill";

interface TopBarProps {
  activeTopic: Topic;
  onTopicChange: (topic: Topic) => void;
  isLive: boolean;
  isLoading: boolean;
  isOffline: boolean;
  /** The timeline's replay is playing (see StatusPill). */
  isReplay?: boolean;
  /** The topic pills' nav (TopicFilter). */
  topicsRef?: Ref<HTMLElement>;
}

/**
 * One grid with three tracks (brand | topics | status), so the regions can
 * shrink or scroll but never overlap. Layout rules are in soft-orbit.css.
 */
export default function TopBar({
  activeTopic,
  onTopicChange,
  isLive,
  isLoading,
  isOffline,
  isReplay = false,
  topicsRef,
}: TopBarProps) {
  return (
    <header className="topbar">
      {/* Branding: frozen lockup (tokens.md). Colours, motto font and line
          height are pinned so the Soft Orbit body text styles don't reach it.
          The grid places it at 20px/24px (12px on phones). */}
      <div className="topbar-left flex items-center gap-2 sm:gap-3" data-testid="brand">
        <img
          src="/Orbis_logo_50_resize.png"
          alt="Orbis"
          className="h-7 w-7 sm:h-10 sm:w-10"
          style={{ filter: "drop-shadow(0 0 12px rgba(0, 212, 255, 0.5))" }}
        />
        <div>
          <h1
            className="text-sm font-bold tracking-[0.2em] text-[var(--brand-wordmark-color)] uppercase sm:text-lg"
            style={{
              fontFamily: "var(--font-brand), sans-serif",
              textShadow: "0 0 30px rgba(0, 212, 255, 0.4)",
            }}
          >
            Orbis
          </h1>
          <p
            className="hidden text-[9px] leading-[13.5px] font-medium tracking-[0.3em] text-[var(--text-motto)] uppercase sm:block"
            style={{ fontFamily: "system-ui, -apple-system, sans-serif" }}
          >
            Every Story, Everywhere
          </p>
        </div>
      </div>

      <div className="topbar-center">
        <TopicFilter activeTopic={activeTopic} onTopicChange={onTopicChange} navRef={topicsRef} />
      </div>

      <div className="topbar-right">
        <StatusPill
          isLive={isLive}
          isLoading={isLoading}
          isOffline={isOffline}
          isReplay={isReplay}
        />
        <Link href="/about" title="About Orbis" className="pillbar pill lg">
          About
        </Link>
      </div>
    </header>
  );
}
