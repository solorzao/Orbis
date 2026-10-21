"use client";

import { useEffect, useRef, type CSSProperties } from "react";
import { sentimentKey } from "@/lib/clustering";
import {
  QUAD_KEYS,
  QUAD_LABELS,
  dayWords,
  quadSide,
  quadWords,
  relationDays,
  relationEnds,
  relationLensLabel,
  sampleQuad,
  type QuadKey,
  type Relation,
} from "@/lib/relations";
import { isWebUrl } from "@/hooks/useAgent";
import type { RelationEntry } from "@/types/news";

interface RelationInspectorProps {
  entry: RelationEntry;
  onClose: () => void;
  onMinimize: () => void;
}

/** A side's colour: the arcs' own token. */
const sideStyle = (key: QuadKey) =>
  ({ "--c": `var(--arc-relation-${quadSide(key)})` }) as CSSProperties;

/** One decimal with its sign, a true minus: "−3.1", "+2.4". */
function signed(x: number): string {
  const r = Math.round(x * 10) / 10;
  return (r > 0 ? "+" : r < 0 ? "−" : "±") + Math.abs(r).toFixed(1);
}

const clamp = (x: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, x));

/** Tone's dot: GDELT's tone (usually −10 to +10) on the sentiment scale. */
const toneStyle = (tone: number) =>
  ({ "--sc": `var(--sentiment-${sentimentKey(clamp(tone / 10, -1, 1))})` }) as CSSProperties;

/** A country's name in the pair, by its code. */
const nameOf = (rel: Relation, iso: string) =>
  rel.a.iso === iso ? rel.a.name : rel.b.iso === iso ? rel.b.name : iso;

/**
 * The relation inspector in the side panel's Inspect tab (the link
 * inspector's .insp structure): two countries' reported events over the
 * 7-day lens, with the caveat that GDELT machine-codes them from news reports
 * and they are not verified facts. Its readouts, every class whatever the
 * layer's class switch says (decision 7), each direction, the days, and
 * sample reports. Until the detail lands it shows the arc's numbers; named
 * from the arc's acting country, as the arc and its pill are. Not pinnable
 * (decision 9).
 */
export default function RelationInspector({ entry, onClose, onMinimize }: RelationInspectorProps) {
  const { detail } = entry;
  const headingRef = useRef<HTMLHeadingElement>(null);

  // Opened with the focus nowhere (the list row that opened it went with the
  // list, or a click on the globe): it starts on the heading, not the page.
  useEffect(() => {
    const active = document.activeElement;
    if (!active || active === document.body) headingRef.current?.focus();
  }, []);

  // Named from the arc's acting country; the numbers are the detail's once it lands.
  const [from, to] = relationEnds(entry.relation);
  const rel = detail?.relation ?? entry.relation;
  const lens = detail?.lens ?? entry.lens;
  const kicker = lens ? relationLensLabel(lens, "Relation") : "Relation · last 7 days";
  const total = Math.max(
    1,
    QUAD_KEYS.reduce((sum, k) => sum + rel.quad[k], 0),
  );
  const days = detail ? relationDays(detail.daily, detail.lens) : [];
  const dayMax = Math.max(1, ...days.map((d) => Math.max(d.cooperation, d.conflict)));

  return (
    <div
      data-testid="relation-inspector"
      className="insp"
      aria-busy={entry.detailLoading || undefined}
      // Escape inside the inspector minimizes it, as in a place's panel
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onMinimize();
        }
      }}
    >
      <div>
        <div className="insp-head">
          <div className="min-w-0">
            <p className="lbl insp-kicker">
              <span>{kicker}</span>
            </p>
            <h2 ref={headingRef} className="insp-title" tabIndex={-1}>
              {from.name} <span className="insp-amp">and</span> {to.name}
            </h2>
          </div>
          <div className="end">
            <button
              type="button"
              className="iconbtn"
              aria-label="Minimize panel"
              title="Keep in recent places and links"
              onClick={onMinimize}
            >
              <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
                <path d="M2.5 6h7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
              </svg>
            </button>
            <button type="button" className="iconbtn" aria-label="Close panel" onClick={onClose}>
              <svg width="11" height="11" viewBox="0 0 12 12" aria-hidden="true">
                <path
                  d="M2 2l8 8M10 2l-8 8"
                  stroke="currentColor"
                  strokeWidth="1.4"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          </div>
        </div>
        <p className="insp-lead">
          Events GDELT machine-coded from news reports: who did what to whom, as reported. Not
          verified facts; one report can yield several events.
        </p>
      </div>

      {entry.notFound ? (
        <p className="insp-status">No reported events between them in the last 7 days.</p>
      ) : (
        <>
          <div className="readouts rel-readouts" data-testid="relation-readouts">
            <div className="ro" role="group" aria-label="Events">
              <span aria-hidden="true">Events</span>
              <b>{rel.n}</b>
            </div>
            <div className="ro" role="group" aria-label="Outlets">
              <span aria-hidden="true">Outlets</span>
              <b title="At least: up to 8 outlets are kept per day and class">{rel.outlets}</b>
            </div>
            <div className="ro" role="group" aria-label="Goldstein">
              <span aria-hidden="true">Goldstein</span>
              <b>{signed(rel.goldstein)}</b>
              <small className="ro-sub">event-type score, −10 conflict to +10 cooperation</small>
            </div>
            <div className="ro" role="group" aria-label="Tone">
              <span aria-hidden="true">Tone</span>
              <b className="ro-text">
                <span className="sent" style={toneStyle(rel.tone)}>
                  {signed(rel.tone)}
                </span>
              </b>
              <small className="ro-sub">first reports</small>
            </div>
          </div>

          <div>
            <p className="lbl insp-kicker">
              <span>By class</span>
            </p>
            <ul className="rel-classes" aria-label="Reported events by class">
              {QUAD_KEYS.map((key) => {
                const pct = Math.round((rel.quad[key] / total) * 100);
                return (
                  <li key={key} className="rel-class" style={sideStyle(key)}>
                    <span className="rel-class-name">{QUAD_LABELS[key]}</span>
                    <span className="rel-class-n">{rel.quad[key]}</span>
                    <span className="rel-class-pct">{pct}%</span>
                    <span className="rel-bar" aria-hidden="true">
                      <span style={{ width: `${pct}%` }} />
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>

          {detail && detail.directions.length > 0 && (
            <div>
              <p className="lbl insp-kicker">
                <span>Who acted</span>
              </p>
              <ul className="rel-directions" aria-label="Directions">
                {detail.directions.map((d) => (
                  <li key={`${d.from}-${d.to}`}>
                    {nameOf(rel, d.from)} → {nameOf(rel, d.to)}: {d.n}{" "}
                    {d.n === 1 ? "event" : "events"}, {quadWords(d.quad, d.n)}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {detail && days.length > 0 && (
            <div>
              <p className="lbl insp-kicker">
                <span>By day (UTC)</span>
              </p>
              <div className="rel-days" aria-hidden="true">
                {days.map((d) => (
                  <div key={d.day} className="rel-day" data-day={d.day}>
                    <span className="rel-day-bars">
                      <span
                        className="b sw-coop"
                        style={{ height: `${(d.cooperation / dayMax) * 100}%` }}
                      />
                      <span
                        className="b sw-conf"
                        style={{ height: `${(d.conflict / dayMax) * 100}%` }}
                      />
                    </span>
                    <span className="rel-day-lbl">{dayWords(d.day).split(" ")[0]}</span>
                  </div>
                ))}
              </div>
              <table className="sr-only" aria-label="Reported events by UTC day">
                <thead>
                  <tr>
                    <th scope="col">Day (UTC)</th>
                    <th scope="col">Cooperation</th>
                    <th scope="col">Conflict</th>
                  </tr>
                </thead>
                <tbody>
                  {days.map((d) => (
                    <tr key={d.day}>
                      <th scope="row">{dayWords(d.day)}</th>
                      <td>{d.cooperation}</td>
                      <td>{d.conflict}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="scrim insp-list">
            <p className="lbl insp-list-lbl">
              <span>Sample reports</span>
            </p>
            {entry.detailLoading && (
              <>
                <p className="insp-status">Fetching the breakdown…</p>
                {[0, 1, 2].map((i) => (
                  <div key={i} className="art" aria-hidden="true">
                    <span className="skel" />
                    <span className="skel short" />
                  </div>
                ))}
              </>
            )}
            {entry.detailError && (
              <p className="insp-status">Couldn&apos;t load this relation&apos;s detail.</p>
            )}
            {detail && detail.samples.length === 0 && (
              <p className="insp-status">No sample reports kept for these events.</p>
            )}
            {detail && detail.samples.length > 0 && (
              <ul className="insp-stories" aria-label="Sample reports">
                {detail.samples.map((s) => {
                  const quad = sampleQuad(s.quadClass);
                  const other = s.from === rel.a.iso ? rel.b.iso : rel.a.iso;
                  const name = s.title ?? s.outlet;
                  return (
                    <li key={s.url} className="art">
                      {isWebUrl(s.url) ? (
                        <a className="h" href={s.url} target="_blank" rel="noopener noreferrer">
                          {name}
                        </a>
                      ) : (
                        <span className="h">{name}</span>
                      )}
                      <div className="m">
                        <span>{s.outlet}</span>
                        <span>{dayWords(s.day)}</span>
                        <span className="art-tag" style={sideStyle(quad)}>
                          {QUAD_LABELS[quad]}
                        </span>
                        <span>
                          {nameOf(rel, s.from)} → {nameOf(rel, other)}
                        </span>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  );
}
