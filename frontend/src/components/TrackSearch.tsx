"use client";

import { useEffect, useId, useMemo, useState, type KeyboardEvent, type Ref } from "react";
import { useTrackSearch } from "@/hooks/useTrackSearch";
import { cellKey } from "@/lib/cells";
import {
  countLabel,
  searchAnnouncement,
  searchPlaces,
  type EntityType,
  type ThreadResult,
} from "@/lib/entities";
import { placeName } from "@/lib/hoverCard";
import type { GlobePoint } from "@/types/news";

export const TRACK_PLACEHOLDER = "Track a place, person, organisation or thread";

type Option =
  | { kind: "place"; key: string; label: string; count: string; name: string; point: GlobePoint }
  | {
      kind: "person" | "org";
      key: string;
      label: string;
      count: string;
      name: string;
      type: EntityType;
    }
  | { kind: "thread"; key: string; label: string; count: null; name: string; thread: ThreadResult };

const GROUPS = [
  { kind: "place", label: "Places" },
  { kind: "person", label: "People" },
  { kind: "org", label: "Organisations" },
  { kind: "thread", label: "Threads" },
] as const;

const stories = (n: string, one: boolean) => `${n} ${one ? "story" : "stories"}`;

interface TrackSearchProps {
  /** The top bar's pill (from 1180px), or the sheet's box below. */
  variant: "bar" | "sheet";
  /** The globe's loaded places: searched here, at once. */
  points: readonly GlobePoint[];
  /** A place: fly there and open it. */
  onPlace: (point: GlobePoint) => void;
  /** A person or organisation: track them. */
  onEntity: (entity: { name: string; type: EntityType }) => void;
  /** A thread: select it. */
  onThread: (thread: ThreadResult) => void;
  /** The settled results' counts ("" when closed), for the page's polite announcer. */
  onAnnounce?: (text: string) => void;
  /** Escape on an empty box, or the sheet's Close search. */
  onDismiss?: () => void;
  autoFocus?: boolean;
  inputRef?: Ref<HTMLInputElement>;
}

/**
 * Track search (mockup `label.pillbar.search`): one box for places, people,
 * organisations and story threads, as the ARIA 1.2 combobox with a listbox
 * popup (list autocomplete, manual selection). The places come from the
 * globe at once; the rest from /api/search once typing pauses. Up and Down
 * move through the options (wrapping), Enter chooses one (the first, when
 * none is active), Escape closes the list, then clears the box, then leaves.
 */
export default function TrackSearch({
  variant,
  points,
  onPlace,
  onEntity,
  onThread,
  onAnnounce,
  onDismiss,
  autoFocus = false,
  inputRef,
}: TrackSearchProps) {
  const uid = useId();
  const listId = `${uid}-list`;
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const { results, loading, error } = useTrackSearch(query);

  const places = useMemo(() => searchPlaces(points, query), [points, query]);
  const options = useMemo<Option[]>(() => {
    const list: Option[] = places.map((p) => ({
      kind: "place",
      key: `place:${cellKey(p.lat, p.lng)}`,
      name: placeName(p),
      count: p.count.toLocaleString("en-GB"),
      label: `${placeName(p)}, ${stories(p.count.toLocaleString("en-GB"), p.count === 1)}`,
      point: p,
    }));
    for (const e of [...(results?.people ?? []), ...(results?.orgs ?? [])]) {
      const count = countLabel(e.n, e.capped);
      list.push({
        kind: e.type,
        key: `${e.type}:${e.name}`,
        name: e.name,
        type: e.type,
        count,
        label: `${e.name}, ${stories(count, count === "1")} this week`,
      });
    }
    for (const t of results?.threads ?? []) {
      list.push({
        kind: "thread",
        key: `thread:${t.id}`,
        name: t.title,
        count: null,
        label: t.title,
        thread: t,
      });
    }
    return list;
  }, [places, results]);

  const shown = open && query.trim().length > 0;
  const activeIndex = shown ? options.findIndex((o) => o.key === activeKey) : -1;
  const optionId = (i: number) => `${uid}-opt-${i}`;
  const activeOption = activeIndex >= 0 ? optionId(activeIndex) : undefined;

  // The list's note: while the server is asked, when it failed, or when nothing matched.
  const note = !shown
    ? null
    : loading
      ? "Searching people, organisations and threads…"
      : error
        ? "Search unavailable right now"
        : options.length === 0
          ? "No matches"
          : null;
  // What a screen reader hears: the counts once the server has answered (or
  // there was nothing to ask), nothing while the list is closed or gone.
  const counts = {
    places: places.length,
    people: results?.people.length ?? 0,
    orgs: results?.orgs.length ?? 0,
    threads: results?.threads.length ?? 0,
  };
  const announcement = !shown
    ? ""
    : loading
      ? null // not yet: say it once, when it settles
      : error
        ? places.length > 0
          ? `${searchAnnouncement(counts)}. Search unavailable right now`
          : "Search unavailable right now"
        : searchAnnouncement(counts);
  useEffect(() => {
    if (announcement !== null) onAnnounce?.(announcement);
  }, [announcement, onAnnounce]);
  useEffect(() => () => onAnnounce?.(""), [onAnnounce]);

  // The active option stays in view as the arrows move through a long list.
  useEffect(() => {
    if (activeOption) document.getElementById(activeOption)?.scrollIntoView?.({ block: "nearest" });
  }, [activeOption]);

  const choose = (option: Option) => {
    setQuery("");
    setOpen(false);
    setActiveKey(null);
    if (option.kind === "place") onPlace(option.point);
    else if (option.kind === "thread") onThread(option.thread);
    else onEntity({ name: option.name, type: option.type });
  };

  const move = (step: 1 | -1) => {
    if (options.length === 0) return;
    const from = activeIndex < 0 ? (step === 1 ? -1 : 0) : activeIndex;
    const next = (from + step + options.length) % options.length;
    setActiveKey(options[next].key);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    switch (e.key) {
      case "ArrowDown":
      case "ArrowUp":
        e.preventDefault();
        if (!shown) {
          if (!query.trim()) return;
          setOpen(true);
          const edge = e.key === "ArrowDown" ? options[0] : options.at(-1);
          setActiveKey(edge?.key ?? null);
          return;
        }
        move(e.key === "ArrowDown" ? 1 : -1);
        return;
      case "Enter": {
        if (!shown) return;
        const option = options[activeIndex] ?? options[0];
        if (!option) return;
        e.preventDefault();
        choose(option);
        return;
      }
      case "Escape":
        // Ours alone: the hover card's and the panels' Escape must not fire too.
        e.stopPropagation();
        e.preventDefault();
        if (shown) {
          setOpen(false);
          setActiveKey(null);
        } else if (query) {
          setQuery("");
        } else {
          onDismiss?.();
        }
        return;
    }
  };

  const grouped = GROUPS.map((g) => ({
    ...g,
    options: options
      .map((option, index) => ({ option, index }))
      .filter(({ option }) => option.kind === g.kind),
  })).filter((g) => g.options.length > 0);

  return (
    <div
      className={`track track-${variant}`}
      data-testid={variant === "bar" ? "track-search" : "track-search-sheet"}
    >
      <label className={variant === "bar" ? "pillbar search" : "search sheet-search"}>
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
        <input
          ref={inputRef}
          type="text"
          role="combobox"
          aria-label={TRACK_PLACEHOLDER}
          placeholder={TRACK_PLACEHOLDER}
          aria-expanded={shown}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={activeOption}
          autoComplete="off"
          spellCheck={false}
          enterKeyHint="search"
          maxLength={80}
          autoFocus={autoFocus} // the sheet's search opens to be typed in
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
            setActiveKey(null);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => {
            setOpen(false);
            setActiveKey(null);
          }}
          onKeyDown={onKeyDown}
        />
        {variant === "bar" && <kbd aria-hidden="true">/</kbd>}
      </label>
      {variant === "sheet" && (
        <button
          type="button"
          className="iconbtn"
          aria-label="Close search"
          onClick={() => onDismiss?.()}
        >
          <svg width="11" height="11" viewBox="0 0 12 12" aria-hidden="true">
            <path
              d="M2 2l8 8M10 2l-8 8"
              stroke="currentColor"
              strokeWidth="1.4"
              strokeLinecap="round"
            />
          </svg>
        </button>
      )}
      {/* Over the page from the top bar (glass); in the sheet, in its flow. */}
      <div className={variant === "bar" ? "glass track-pop" : "track-pop"} hidden={!shown}>
        <div id={listId} role="listbox" aria-label="Track results">
          {grouped.map((g) => (
            <div key={g.kind} role="group" aria-labelledby={`${uid}-${g.kind}`}>
              <div id={`${uid}-${g.kind}`} role="presentation" className="lbl track-group">
                {g.label}
              </div>
              {g.options.map(({ option, index }) => (
                <div
                  key={option.key}
                  id={optionId(index)}
                  role="option"
                  aria-selected={index === activeIndex}
                  aria-label={option.label}
                  className="track-opt"
                  data-kind={option.kind}
                  // Keep the focus in the box: a click must not blur it first.
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => choose(option)}
                >
                  <span className="t">{option.name}</span>
                  {option.count !== null && <span className="num">{option.count}</span>}
                </div>
              ))}
            </div>
          ))}
        </div>
        {note && <p className="track-note">{note}</p>}
      </div>
    </div>
  );
}
