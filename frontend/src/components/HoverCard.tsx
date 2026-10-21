"use client";

import { useId, useState, type CSSProperties, type ReactNode, type Ref } from "react";
import type { ApiPlacePreview } from "@/lib/api";
import { formatScore, sentimentKey } from "@/lib/clustering";
import {
  cardCountLabel,
  cardLabel,
  formatAgo,
  placeName,
  sparkPaths,
  topicMixList,
} from "@/lib/hoverCard";
import { looksLikePhoto, safeImageUrl, veilsImage } from "@/lib/imageSafety";
import type { TimeWindow } from "@/lib/timeWindow";
import type { GlobeLead, GlobePoint, Topic } from "@/types/news";

/** Each topic's glyph (mockup GLYPH), shown when a place's lead has no usable image. */
const GLYPHS: Record<Topic, ReactNode> = {
  All: (
    <>
      <circle cx="12" cy="12" r="8" strokeWidth="1.4" />
      <path d="M4 12h16M12 4c3 3 3 13 0 16M12 4c-3 3-3 13 0 16" strokeWidth="1.2" />
    </>
  ),
  Economy: <path d="M4 18V12M9 18V8M14 18V10M19 18V5" strokeWidth="1.6" strokeLinecap="round" />,
  Politics: <path d="M4 9l8-5 8 5M6 9v8M10 9v8M14 9v8M18 9v8M3 19h18" strokeWidth="1.4" />,
  Conflict: (
    <>
      <circle cx="12" cy="12" r="8" strokeWidth="1.4" />
      <path d="M12 7v5l3 2" strokeWidth="1.4" />
    </>
  ),
  Technology: (
    <>
      <rect x="6" y="6" width="12" height="12" rx="3" strokeWidth="1.4" />
      <path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3" strokeWidth="1.4" />
    </>
  ),
  Climate: <path d="M7 17a4 4 0 0 1 .5-8A6 6 0 0 1 19 10a3.5 3.5 0 0 1-1 7z" strokeWidth="1.4" />,
  Health: <path d="M12 6v12M6 12h12" strokeWidth="1.8" strokeLinecap="round" />,
};

const topicVar = (topic: Topic) =>
  ({ "--c": `var(--topic-${topic.toLowerCase()})` }) as CSSProperties;

function Glyph({ topic }: { topic: Topic }) {
  return (
    <div className="thumb glyph" style={topicVar(topic)} title="No image">
      <svg
        width="30"
        height="30"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        aria-hidden="true"
      >
        {GLYPHS[topic]}
      </svg>
    </div>
  );
}

/**
 * The lead's image (lib/imageSafety): https only, no referrer, lazy. A logo,
 * a failed load or an image that isn't photo-shaped gives way to the topic's
 * glyph. A sensitive lead's image (a conflict tag) is blurred behind a veil until Show.
 */
function Thumb({
  lead,
  revealed,
  onReveal,
}: {
  lead: GlobeLead;
  revealed: ReadonlySet<string>;
  onReveal: (url: string) => void;
}) {
  const url = safeImageUrl(lead.imageUrl);
  // The URL that failed, so a new lead's image gets its own chance.
  const [failed, setFailed] = useState<string | null>(null);
  if (!url || failed === url) return <Glyph topic={lead.topic} />;
  const veiled = veilsImage(lead.sensitive, revealed.has(url));
  return (
    <div className={veiled ? "thumb veiled" : "thumb"}>
      {/* A third-party image of unknown size: next/image would proxy it. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={url}
        alt=""
        referrerPolicy="no-referrer"
        loading="lazy"
        decoding="async"
        onError={() => setFailed(url)}
        onLoad={(e) => {
          const img = e.currentTarget;
          if (!looksLikePhoto(img.naturalWidth, img.naturalHeight)) setFailed(url);
        }}
      />
      {veiled && (
        <button type="button" className="veil" onClick={() => onReveal(url)}>
          Conflict image hidden <span>· Show</span>
        </button>
      )}
    </div>
  );
}

function Spark({ values }: { values: readonly number[] }) {
  const gradient = `spark-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const { line, area } = sparkPaths(values, 150, 30);
  return (
    <span className="spark" title="Stories per hour over 24 hours">
      <svg width="150" height="30" aria-hidden="true" data-testid="hover-spark">
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
        />
      </svg>
    </span>
  );
}

interface HoverCardProps {
  point: GlobePoint;
  timeWindow: TimeWindow;
  /** When the card showed (Date.now()), for the lead's age. */
  now: number;
  /** The dwell data, once it has come (useHoverPreview). */
  preview: ApiPlacePreview | null;
  previewLoading: boolean;
  /** Conflict images the visitor has revealed this session. */
  revealed: ReadonlySet<string>;
  onReveal: (url: string) => void;
  /** On a touch screen: docked above the bottom row, with an Open stories pill. */
  docked?: boolean;
  /** While Links is on: how many countries the place's country is linked to. */
  linkedCountries?: number | null;
  onOpen?: () => void;
  /** Track a name the place's stories mention (the entity tracker); inert pills without it. */
  onTrack?: (entity: { name: string; type: "person" | "org" }) => void;
  onPointerEnter?: () => void;
  onPointerLeave?: () => void;
  ref?: Ref<HTMLElement>;
}

/**
 * The city hover card (mockup `renderRecon`): what a place is talking about
 * before the visitor commits to a click. The first glance comes from the
 * globe's own payload; the sparkline, names and AI brief follow after a
 * dwell (useHoverPreview), with a skeleton meanwhile. GlobeHud places it.
 * It is no live region: it mounts with its content, which screen readers
 * miss, so the page announces cardLabel from a node that is always there.
 */
export default function HoverCard({
  point,
  timeWindow,
  now,
  preview,
  previewLoading,
  revealed,
  onReveal,
  docked = false,
  linkedCountries = null,
  onOpen,
  onTrack,
  onPointerEnter,
  onPointerLeave,
  ref,
}: HoverCardProps) {
  const place = placeName(point);
  const { lead } = point;
  const tone = point.tone ?? 0;
  const mix = topicMixList(point.topicMix);
  const topTwo = [...mix].sort((a, b) => b.share - a.share).slice(0, 2);
  const loading = !preview && previewLoading;

  return (
    <article
      ref={ref}
      className={docked ? "glass recon docked" : "glass recon"}
      data-testid="hover-card"
      aria-label={cardLabel(point)}
      onPointerEnter={onPointerEnter}
      onPointerLeave={onPointerLeave}
    >
      <div className={lead ? "top" : "top solo"}>
        {lead && <Thumb lead={lead} revealed={revealed} onReveal={onReveal} />}
        <div>
          <p className="place">
            {place}
            {point.countryCode && <small>{point.countryCode}</small>}
          </p>
          <div className="count">{cardCountLabel(point.count, timeWindow)}</div>
          {preview ? <Spark values={preview.spark} /> : loading && <span className="skel spark" />}
        </div>
      </div>
      <div className="body">
        {lead && (
          <div>
            <p className="hl">{lead.title}</p>
            <div className="src">
              <span>{lead.sourceName}</span>
              <span>{formatAgo(lead.publishedAt, now)}</span>
            </div>
          </div>
        )}
        {mix.length > 0 && (
          <div className="kv">
            <span>Topic mix</span>
            <div className="mix" aria-hidden="true">
              {mix.map((m) => (
                <span key={m.topic} style={{ ...topicVar(m.topic), flex: m.share }} />
              ))}
            </div>
            <span />
            <div className="mixl">
              {topTwo.map((m) => (
                <span key={m.topic}>
                  <i style={topicVar(m.topic)} />
                  {m.topic} {Math.round(m.share * 100)}%
                </span>
              ))}
            </div>
          </div>
        )}
        <div className="kv">
          <span>Tone</span>
          <div className="tone" role="img" aria-label={`Headline tone ${formatScore(tone)}`}>
            <i style={{ left: `${Math.round(((tone + 1) / 2) * 1000) / 10}%` }} />
          </div>
          <span
            className="sent"
            style={{ "--sc": `var(--sentiment-${sentimentKey(tone)})` } as CSSProperties}
          >
            {formatScore(tone)}
          </span>
        </div>
        {preview && preview.entities.length > 0 && (
          // Buttons that track the name once something can (the entity tracker).
          <div className="chips">
            {preview.entities.slice(0, 3).map((e) =>
              onTrack ? (
                <button
                  key={`${e.type}:${e.name}`}
                  type="button"
                  className="pill"
                  title={`${e.n} stories`}
                  aria-label={`Track ${e.name}`}
                  onClick={() => onTrack({ name: e.name, type: e.type })}
                >
                  {e.name}
                </button>
              ) : (
                <span key={`${e.type}:${e.name}`} className="pill" title={`${e.n} stories`}>
                  {e.name}
                </span>
              ),
            )}
          </div>
        )}
        {loading && <span className="skel short" />}
        {preview?.brief && (
          <p className="brief scrim">
            <span className="clamp">
              <span className="ai">AI</span>
              {preview.brief}
            </span>
          </p>
        )}
      </div>
      <div className="foot">
        {docked ? (
          <button type="button" className="pill on" onClick={onOpen}>
            Open stories
          </button>
        ) : (
          <span>Click to open</span>
        )}
        {!!linkedCountries && (
          <span className="foot-links">
            {linkedCountries} linked {linkedCountries === 1 ? "country" : "countries"}
          </span>
        )}
      </div>
    </article>
  );
}
