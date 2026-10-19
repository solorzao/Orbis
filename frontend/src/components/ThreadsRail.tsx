"use client";

import { useId } from "react";
import { THREADS_SHOWN, velocityShare, type Thread, type ThreadDetail } from "@/lib/threads";

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
}

const plural = (n: number, one: string, many: string) =>
  `${n.toLocaleString("en-GB")} ${n === 1 ? one : many}`;

/** "{n} regions": the countries it reached. */
const regions = (t: Thread) => plural(t.countries.length, "region", "regions");

/**
 * Threads (mockup `section.threads`, `.th`): the same developing story across
 * outlets and places, fastest first, up to 10 rows. A row selects its thread
 * and opens it inline; the selected one again closes it. From 1180px a left
 * glass panel under the since strip; below, the sheet's Threads tab.
 */
export default function ThreadsRail({
  variant,
  threads,
  status,
  loading,
  selected,
  onSelect,
}: ThreadsRailProps) {
  const uid = useId();
  const shown = threads.slice(0, THREADS_SHOWN);
  const count = !loading && shown.length > 0 ? `${threads.length} active` : null;

  const list = (
    <>
      {status && <p className="th-note">{status}</p>}
      {!status && loading && shown.length === 0 && (
        <p className="th-note">Finding developing stories…</p>
      )}
      {shown.length > 0 && (
        <ul className="th-list" aria-label="Developing stories" aria-busy={loading || undefined}>
          {shown.map((t) => {
            const open = selected?.id === t.id;
            return (
              <li key={t.id}>
                <button
                  type="button"
                  className="th"
                  aria-expanded={open}
                  aria-controls={open ? `${uid}-detail` : undefined}
                  aria-label={`${t.title}, ${t.status}, ${plural(t.stories, "story", "stories")}, ${regions(t)}, ${plural(t.outlets, "outlet", "outlets")}`}
                  onClick={() => onSelect(open ? null : { id: t.id, title: t.title })}
                >
                  <span className="t">{t.title}</span>
                  <span className="num">{t.stories}</span>
                  <span className="m">
                    <span className="th-status" data-s={t.status}>
                      {t.status}
                    </span>
                    <span>{regions(t)}</span>
                    <span>{plural(t.outlets, "outlet", "outlets")}</span>
                    <span className="bar">
                      <i style={{ width: `${velocityShare(t, threads)}%` }} />
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
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
