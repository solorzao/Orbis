"use client";

import { useEffect, useId, useRef, type CSSProperties, type KeyboardEvent } from "react";
import { formatScore, sentimentKey } from "@/lib/clustering";
import {
  CONSTELLATION,
  constellation,
  pivotType,
  rampSince,
  shortDate,
  trendLabel,
  typeLabel,
  type EntityDossier as Dossier,
  type EntityPlace,
  type EntityRef,
  type EntityType,
} from "@/lib/entities";
import { formatAgo, sparkPaths } from "@/lib/hoverCard";
import { isWebUrl } from "@/hooks/useAgent";
import { useMinuteNow } from "@/hooks/useMinuteNow";
import { entityItem } from "@/lib/board";
import { entitySnapshot } from "@/lib/boardSnapshots";
import PinButton from "@/components/PinButton";

interface EntityDossierProps {
  /** What is tracked, as asked (a dossier may spell it otherwise). */
  entity: EntityRef;
  dossier: Dossier | null;
  loading: boolean;
  /** No person or organisation has the name (a 404). */
  notFound: boolean;
  error: boolean;
  /** Track a name in the same coverage instead. */
  onPivot: (entity: { name: string; type: EntityType }) => void;
  /** A top place: fly there and open it. */
  onPlace: (place: EntityPlace) => void;
  onStop: () => void;
  onMinimize: () => void;
}

const sentStyle = (score: number) =>
  ({ "--sc": `var(--sentiment-${sentimentKey(score)})` }) as CSSProperties;

const plural = (n: number, one: string, many: string) =>
  `${n.toLocaleString("en-GB")} ${n === 1 ? one : many}`;

/** Stories per day, as a small line (the hover card's sparkline). */
function Timeline({ values, label }: { values: number[]; label: string }) {
  const gradient = `ent-spark-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const { line, area } = sparkPaths(values, 300, 32);
  return (
    <svg
      className="ent-spark"
      viewBox="0 0 300 32"
      preserveAspectRatio="none"
      width="100%"
      height="32"
      role="img"
      aria-label={`${label}: ${values.join(", ")}`}
    >
      <defs>
        <linearGradient id={gradient} x1="0" x2="1">
          <stop offset="0" stopColor="var(--accent-primary)" />
          <stop offset="1" stopColor="var(--accent-lavender)" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gradient})`} opacity="0.18" />
      <path
        d={line}
        fill="none"
        stroke={`url(#${gradient})`}
        strokeWidth="1.5"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

/**
 * "Appears in the same coverage as" (mockup drawConstellation): the names
 * most often in the entity's stories, around it, sized by those stories.
 * A name the graph can track is a button that pivots to it.
 */
function Constellation({
  dossier,
  onPivot,
}: {
  dossier: Dossier;
  onPivot: (entity: { name: string; type: EntityType }) => void;
}) {
  const uid = useId();
  const gradient = `ent-core-${uid.replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const nodes = constellation(dossier.coMentions);
  const C = CONSTELLATION;
  return (
    <div className="scrim ent-co">
      <p className="lbl" id={`${uid}-lbl`}>
        <span>Appears in the same coverage as</span>
      </p>
      {nodes.length === 0 ? (
        <p className="insp-note">No other names in its stories yet.</p>
      ) : (
        <svg
          className="constellation"
          viewBox={`0 0 ${C.width} ${C.height}`}
          width="100%"
          role="group"
          aria-labelledby={`${uid}-lbl`}
        >
          <defs>
            <radialGradient id={gradient}>
              <stop offset="0" stopColor="var(--accent-primary)" />
              <stop offset="1" stopColor="var(--accent-lavender)" />
            </radialGradient>
          </defs>
          <g aria-hidden="true">
            {nodes.map((node) => (
              <line
                key={node.name}
                x1={C.cx}
                y1={C.cy}
                x2={node.x}
                y2={node.y}
                stroke="var(--orbit-tick)"
                strokeWidth={node.width}
              />
            ))}
            <circle cx={C.cx} cy={C.cy} r="10" fill={`url(#${gradient})`} />
          </g>
          {nodes.map((node) => {
            const type = pivotType(node, dossier.type);
            const stories = `In ${plural(node.n, "story", "stories")} with ${dossier.name}`;
            const body = (
              <>
                <title>{stories}</title>
                <circle cx={node.x} cy={node.y} r={node.r} className="co-node" />
                <text x={node.x} y={node.labelY} textAnchor="middle" aria-hidden="true">
                  {node.label}
                </text>
              </>
            );
            if (!type) {
              return (
                <g key={node.name} className="co" role="img" aria-label={node.name}>
                  {body}
                </g>
              );
            }
            const pivot = () => onPivot({ name: node.name, type });
            return (
              <g
                key={node.name}
                className="co co-track"
                role="button"
                tabIndex={0}
                aria-label={`Track ${node.name}`}
                onClick={pivot}
                onKeyDown={(e: KeyboardEvent<SVGGElement>) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    pivot();
                  }
                }}
              >
                {body}
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}

/**
 * The entity dossier in the Inspect tab (mockup inspectHTML, entity branch):
 * a person or organisation across the week's coverage, its readouts and
 * daily stories, the names in the same coverage, its top places with their
 * tone, and the latest headlines. "Stop tracking", or Escape inside it, ends
 * tracking (and the globe's focus mode); minimizing keeps it. Until tracking
 * holds a week, the week's readout and the timeline say since when.
 */
export default function EntityDossier({
  entity,
  dossier,
  loading,
  notFound,
  error,
  onPivot,
  onPlace,
  onStop,
  onMinimize,
}: EntityDossierProps) {
  const headingRef = useRef<HTMLHeadingElement>(null);

  // Opened with the focus nowhere (a click on the globe, or the sheet's search
  // that closed): it starts on the heading, not the page.
  useEffect(() => {
    const active = document.activeElement;
    if (!active || active === document.body) headingRef.current?.focus();
  }, []);

  const name = dossier?.name ?? entity.name;
  // Now, to the minute: the headlines' ages stay current while it is open.
  const now = useMinuteNow();
  const since = dossier && now !== null ? rampSince(dossier.since, now) : null;
  const weekLabel = since ? `since ${shortDate(since)}` : "7 days";
  const maxN = Math.max(1, ...(dossier?.places.map((p) => p.n) ?? []));

  return (
    <div
      data-testid="entity-dossier"
      className="insp ent"
      aria-busy={loading || undefined}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onStop();
        }
      }}
    >
      <div className="insp-head">
        <div className="min-w-0">
          <p className="lbl insp-kicker">
            <span>Tracking an entity</span>
          </p>
          <h2 ref={headingRef} className="insp-title" tabIndex={-1}>
            {name}
          </h2>
          {dossier && (
            <p className="insp-lead">
              {typeLabel(dossier.type)}. Appears in coverage in{" "}
              {plural(dossier.countries, "country", "countries")}.
            </p>
          )}
        </div>
        <div className="end">
          {dossier && (
            <PinButton
              item={entityItem(dossier.type, dossier.name)}
              snapshot={() => entitySnapshot(dossier)}
            />
          )}
          <button
            type="button"
            className="iconbtn"
            aria-label="Minimize panel"
            title="Keep tracking, in recent places and links"
            onClick={onMinimize}
          >
            <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
              <path d="M2.5 6h7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      </div>

      {loading && (
        <>
          <p className="insp-status">Fetching coverage…</p>
          <div className="readouts ent-readouts" aria-hidden="true">
            {[0, 1, 2].map((i) => (
              <div key={i} className="ro">
                <span className="skel short" />
                <span className="skel" />
              </div>
            ))}
          </div>
        </>
      )}
      {notFound && (
        <p className="insp-status">
          No person or organisation of that name is in this week&apos;s coverage.
        </p>
      )}
      {error && <p className="insp-status">Couldn&apos;t load this dossier.</p>}

      {dossier && (
        <>
          <div className="readouts ent-readouts" data-testid="entity-readouts">
            <div className="ro" role="group" aria-label="24 h">
              <span aria-hidden="true">24 h</span>
              <b>{dossier.h24.toLocaleString("en-GB")}</b>
            </div>
            <div
              className="ro"
              role="group"
              aria-label={since ? `Since ${shortDate(since)}` : "7 days"}
            >
              <span aria-hidden="true">{weekLabel}</span>
              <b>{dossier.d7.toLocaleString("en-GB")}</b>
            </div>
            <div className="ro" role="group" aria-label="Trend">
              <span aria-hidden="true">Trend</span>
              <b title="Stories in the last 24 hours against the 24 hours before">
                {trendLabel(dossier.trend)}
              </b>
            </div>
          </div>

          {dossier.timeline.length > 1 && (
            <div className="ent-timeline">
              <p className="lbl">
                <span>Stories per day</span>
                <span>{since ? `since ${shortDate(since)}` : "last 7 days"}</span>
              </p>
              <Timeline values={dossier.timeline.map((b) => b.n)} label="Stories per day" />
            </div>
          )}

          {dossier.capped && (
            <p className="insp-note">
              Based on the latest {dossier.cap.toLocaleString("en-GB")} mentions.
            </p>
          )}

          <Constellation dossier={dossier} onPivot={onPivot} />

          {dossier.places.length > 0 && (
            <div role="group" aria-label="Top places">
              <p className="lbl">
                <span>Top places</span>
                <span>tone</span>
              </p>
              <ul className="prows">
                {dossier.places.map((p) => (
                  <li key={`${p.lat}:${p.lng}`} className="prow">
                    <button type="button" className="prow-place" onClick={() => onPlace(p)}>
                      {p.place}
                    </button>
                    <span className="b" aria-hidden="true">
                      <i style={{ width: `${Math.round((p.n / maxN) * 100)}%` }} />
                    </span>
                    <span className="sent" style={sentStyle(p.tone)}>
                      <span className="sr-only">{plural(p.n, "story", "stories")}, tone </span>
                      {formatScore(p.tone)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {dossier.headlines.length > 0 && (
            <div className="scrim insp-list">
              <p className="lbl insp-list-lbl">
                <span>Latest headlines</span>
              </p>
              <ul className="insp-stories" aria-label="Latest headlines">
                {dossier.headlines.map((h, i) => (
                  <li key={`${i}:${h.publishedAt}`} className="art">
                    {isWebUrl(h.sourceUrl) ? (
                      <a className="h" href={h.sourceUrl} target="_blank" rel="noopener noreferrer">
                        {h.title}
                      </a>
                    ) : (
                      <span className="h">{h.title}</span>
                    )}
                    <div className="m">
                      <span>{h.sourceName}</span>
                      {h.place && <span>{h.place}</span>}
                      {now !== null && <span>{formatAgo(h.publishedAt, now)}</span>}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      <div className="chips">
        <button type="button" className="pill" onClick={onStop}>
          Stop tracking
        </button>
      </div>
    </div>
  );
}
