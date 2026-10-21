"use client";

import { useId } from "react";
import EntityPills from "@/components/EntityPills";
import PinButton from "@/components/PinButton";
import { threadItem } from "@/lib/board";
import { threadSnapshot } from "@/lib/boardSnapshots";
import {
  THREADS_SHOWN,
  stopLit,
  velocityShare,
  type Thread,
  type ThreadDetail,
} from "@/lib/threads";
import { utcTime, utcWeekday } from "@/lib/timeWindow";

/** A selected thread: its id, and its title for the replay button. */
export interface ThreadRef {
  id: number;
  title: string;
}

interface ThreadsRailProps {
  /** A left glass panel from 1180px, or the sheet's Threads tab below. */
  variant: "rail" | "sheet";
  /** The window's developing stories, fastest first (useThreads). */
  threads: readonly Thread[];
  /** Why it lists nothing (threadsStatus), or null. */
  status: string | null;
  loading: boolean;
  selected: ThreadRef | null;
  /** The selected thread's detail, once loaded (useThread). */
  detail: ThreadDetail | null;
  /** While its spread replays, the places lit so far (null: all). */
  lit: number | null;
  onSelect: (thread: ThreadRef | null) => void;
  /** All {n} stories: the thread's stories in Inspect. */
  onShowStories?: (thread: ThreadDetail) => void;
  /** Track a key entity (PR 17b); the pills are inert without it. */
  onTrack?: (name: string) => void;
}

const plural = (n: number, one: string, many: string) =>
  `${n.toLocaleString("en-GB")} ${n === 1 ? one : many}`;

/** "{n} countries": the countries it reached. */
const countries = (t: Thread) => plural(t.countries.length, "country", "countries");

const when = (iso: string) => {
  const ms = Date.parse(iso);
  return `${utcWeekday(ms)} ${utcTime(ms)}`;
};

/**
 * The selected thread under its row (mockup `.tdetail`): its synopsis (or the
 * lead headline while that is pending), its spread in order of first report,
 * its facts, key entities and all its stories. The list's fields stand in
 * until the detail arrives.
 */
function ThreadDetailPanel({
  id,
  thread,
  detail,
  lit,
  onShowStories,
  onTrack,
}: {
  id: string;
  thread: Thread | null;
  detail: ThreadDetail | null;
  lit: number | null;
  onShowStories?: (thread: ThreadDetail) => void;
  onTrack?: (name: string) => void;
}) {
  const t = detail ?? thread;
  if (!t) {
    return (
      <div id={id} className="tdetail">
        <p className="th-note">Loading the thread…</p>
      </div>
    );
  }
  const spread = detail ? detail.spread : t.places;
  return (
    <div id={id} className="tdetail">
      {t.synopsis ? (
        <p className="syn">
          <span className="ai">AI</span>
          {t.synopsis}
        </p>
      ) : (
        <>
          <p className="syn-note">Synopsis pending; showing the lead headline</p>
          <p className="syn">{t.lead?.title ?? t.title}</p>
        </>
      )}
      {spread.length > 0 && (
        <ol className="route" aria-label="Spread, in order of first report">
          {spread.map((p, i) => (
            <li key={`${p.lat}:${p.lng}`}>
              <span
                className={stopLit(i, lit) ? "stop on" : "stop"}
                title={`First report ${when(p.firstSeen)} UTC`}
              >
                <i aria-hidden="true" />
                <span className="stop-place">{p.place}</span>
                <span className="sr-only">, first reported {when(p.firstSeen)} UTC</span>
              </span>
            </li>
          ))}
        </ol>
      )}
      <ul className="facts" aria-label="Facts">
        <li>
          <span>First seen</span>
          <b>{when(t.firstSeen)}</b>
        </li>
        <li>
          <span>Outlets</span>
          <b>{t.outlets}</b>
        </li>
        <li>
          <span>Countries</span>
          <b>{t.countries.length}</b>
        </li>
      </ul>
      {detail && detail.entities.length > 0 && (
        <div className="th-entities">
          <p className="lbl">
            <span>Key entities</span>
          </p>
          <EntityPills entities={detail.entities} onTrack={onTrack} />
        </div>
      )}
      <div className="chips">
        {detail && onShowStories && (
          <button type="button" className="pill" onClick={() => onShowStories(detail)}>
            All {plural(detail.stories, "story", "stories")}
          </button>
        )}
        <PinButton item={threadItem(t.id)} snapshot={() => threadSnapshot(t)} />
      </div>
    </div>
  );
}

/**
 * Threads (mockup `section.threads`, `.th`): the same developing story across
 * outlets and places, fastest first, up to 10 rows. A row selects its thread
 * and opens it under it; the selected one again closes it. A selected thread
 * the list doesn't hold (a chip's) is held at the top. From 1180px a left
 * glass panel under the since strip; below, the sheet's Threads tab.
 */
export default function ThreadsRail({
  variant,
  threads,
  status,
  loading,
  selected,
  detail,
  lit,
  onSelect,
  onShowStories,
  onTrack,
}: ThreadsRailProps) {
  const uid = useId();
  const listed = threads.slice(0, THREADS_SHOWN);
  const count = !loading && listed.length > 0 ? `${threads.length} active` : null;
  const held = selected !== null && !listed.some((t) => t.id === selected.id);
  // Only the selected thread's detail: a late one for another never shows.
  const ownDetail = detail && selected && detail.id === selected.id ? detail : null;

  const row = (t: Thread | null, ref: ThreadRef) => {
    const open = selected?.id === ref.id;
    const label = t
      ? `${t.title}, ${t.status}, ${plural(t.stories, "story", "stories")}, ${countries(t)}, ${plural(t.outlets, "outlet", "outlets")}`
      : ref.title;
    return (
      <li key={ref.id}>
        <button
          type="button"
          className="th"
          aria-expanded={open}
          aria-controls={open ? `${uid}-detail` : undefined}
          aria-label={label}
          onClick={() => onSelect(open ? null : ref)}
        >
          <span className="t">{ref.title}</span>
          {t && <span className="num">{t.stories}</span>}
          {t && (
            <span className="m">
              <span className="th-status" data-s={t.status}>
                {t.status}
              </span>
              {/* Open, the facts under it say these. */}
              {!open && <span>{countries(t)}</span>}
              {!open && <span>{plural(t.outlets, "outlet", "outlets")}</span>}
              <span className="bar">
                <i style={{ width: `${velocityShare(t, threads)}%` }} />
              </span>
            </span>
          )}
        </button>
        {open && (
          <ThreadDetailPanel
            id={`${uid}-detail`}
            thread={t}
            detail={ownDetail}
            lit={lit}
            onShowStories={onShowStories}
            onTrack={onTrack}
          />
        )}
      </li>
    );
  };

  const list = (
    <>
      {status && <p className="th-note">{status}</p>}
      {!status && loading && listed.length === 0 && !held && (
        <p className="th-note">Finding developing stories…</p>
      )}
      {(listed.length > 0 || held) && (
        <ul className="th-list" aria-label="Developing stories" aria-busy={loading || undefined}>
          {held && selected && row(ownDetail, selected)}
          {listed.map((t) => row(t, { id: t.id, title: t.title }))}
        </ul>
      )}
    </>
  );

  if (variant === "sheet") {
    return (
      <div className="threads-sheet" data-testid="threads-sheet">
        {count && <p className="th-count">{count}</p>}
        {list}
      </div>
    );
  }
  return (
    <section
      className="glass edge threads"
      data-testid="threads-rail"
      aria-labelledby={`${uid}-title`}
    >
      <div className="ghead">
        <h2 id={`${uid}-title`}>Threads</h2>
        {count && <span className="sub">{count}</span>}
      </div>
      <div className="gbody">{list}</div>
    </section>
  );
}
