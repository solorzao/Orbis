"use client";

import type { ReactNode, Ref } from "react";
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
  /** The Track search pill, shown from 1180px (CSS). */
  search?: ReactNode;
  /** Below 1180px a search button opens the same search in the sheet. */
  onSearchOpen?: () => void;
  /** The sheet's search is open. */
  searchOpen?: boolean;
  searchButtonRef?: Ref<HTMLButtonElement>;
}

/**
 * One grid with three tracks (brand | topics | search and status), so the
 * regions can shrink or scroll but never overlap. From 1180px the Track
 * search is a pill before the status; below, a button there opens it in the
 * sheet. Layout rules are in soft-orbit.css.
 */
export default function TopBar({
  activeTopic,
  onTopicChange,
  isLive,
  isLoading,
  isOffline,
  isReplay = false,
  topicsRef,
  search,
  onSearchOpen,
  searchOpen = false,
  searchButtonRef,
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
        {search && <div className="track-bar">{search}</div>}
        {onSearchOpen && (
          <button
            ref={searchButtonRef}
            type="button"
            className="pillbar pill lg search-btn"
            data-testid="search-open"
            aria-label="Track search"
            aria-expanded={searchOpen}
            onClick={onSearchOpen}
          >
            <svg
              width="15"
              height="15"
              viewBox="0 0 14 14"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.3"
              aria-hidden="true"
            >
              <circle cx="6" cy="6" r="4.3" />
              <path d="M9.3 9.3 13 13" strokeLinecap="round" />
            </svg>
          </button>
        )}
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
