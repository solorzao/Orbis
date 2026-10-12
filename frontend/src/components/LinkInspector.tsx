"use client";

import type { CSSProperties } from "react";
import { formatScore, sentimentKey } from "@/lib/clustering";
import { formatAgo } from "@/lib/hoverCard";
import { linkEnds, linkTopic } from "@/lib/links";
import { queryWindowWords } from "@/lib/panelQuery";
import { isWebUrl } from "@/hooks/useAgent";
import type { LinkEntry, NewsArticle, Topic } from "@/types/news";

interface LinkInspectorProps {
  entry: LinkEntry;
  onClose: () => void;
  onMinimize: () => void;
  onExplain: () => void;
}

const sentStyle = (score: number) =>
  ({ "--sc": `var(--sentiment-${sentimentKey(score)})` }) as CSSProperties;

const topicColor = (topic: Topic) =>
  topic === "All" ? "var(--topic-all)" : `var(--topic-${topic.toLowerCase()})`;

function AiSkeleton() {
  return (
    <div className="scrim insp-ai" aria-hidden="true">
      <span className="skel" />
      <span className="skel" />
      <span className="skel short" />
    </div>
  );
}

/**
 * The link inspector in the side panel's Inspect tab (mockup `inspectHTML`,
 * link branch): two countries named in the same stories, with the caveat
 * that coverage is not causation; their readouts, the names and themes they
 * share, the stories that link them, and Claude's explanation on request.
 * Until the detail lands it shows the arc's numbers. The detail sends the
 * pair in code order, so the countries are always named from the link's
 * origin, as the arc and its pill have them.
 */
export default function LinkInspector({
  entry,
  onClose,
  onMinimize,
  onExplain,
}: LinkInspectorProps) {
  const { link, detail, query, explanation, explaining } = entry;
  const [from, to] = linkEnds(link);
  const n = detail?.n ?? link.n;
  const lift = detail?.lift ?? link.lift;
  const tone = detail?.tone ?? link.tone;
  const topic = detail ? linkTopic(detail.topicMix, link.topic) : link.topic;
  const articles = detail?.articles ?? [];
  const shared = detail?.shared ?? [];
  const themes = detail?.themes ?? [];
  const asOf = entry.loadedAt ?? entry.createdAt;
  const windowWords = query.topic
    ? `${queryWindowWords(query)}, ${query.topic}`
    : queryWindowWords(query);

  /** Where a story is placed: its region's first part, else its country. */
  const placeOf = (a: NewsArticle) =>
    a.region?.split(",")[0].trim() ||
    [from, to].find((c) => c.iso === a.countryCode)?.name ||
    a.countryCode;

  return (
    <div
      data-testid="link-inspector"
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
              <span>Link</span>
              <span>covered together, {windowWords}</span>
            </p>
            <h2 className="insp-title">
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
          Named in the same stories. Covered together does not mean cause and effect.
        </p>
      </div>

      <div className="readouts" data-testid="link-readouts">
        <div className="ro" role="group" aria-label="Stories">
          <span aria-hidden="true">Stories</span>
          <b>{n}</b>
        </div>
        <div className="ro" role="group" aria-label="Lift">
          <span aria-hidden="true">Lift</span>
          <b title="How many times more often than chance they are covered together">
            {lift.toFixed(1)}×
          </b>
        </div>
        <div className="ro" role="group" aria-label="Topic">
          <span aria-hidden="true">Topic</span>
          <b className="ro-text" style={{ color: topicColor(topic) }}>
            {topic === "All" ? "Other" : topic}
          </b>
        </div>
        <div className="ro" role="group" aria-label="Tone">
          <span aria-hidden="true">Tone</span>
          <b className="ro-text">
            <span className="sent" style={sentStyle(tone)}>
              {formatScore(tone)}
            </span>
          </b>
        </div>
      </div>

      {shared.length + themes.length > 0 && (
        <div role="group" aria-label="Shared in coverage">
          <p className="lbl insp-kicker">
            <span>Shared in coverage</span>
          </p>
          <div className="chips">
            {/* Inert for now: tracking a name comes with the entity tracker (PR 17). */}
            {shared.map((s) => (
              <span key={`${s.type}:${s.name}`} className="pill" title={`In ${s.n} of the stories`}>
                {s.name}
                <span className="num">{s.n}</span>
              </span>
            ))}
            {themes.map((t) => (
              <span key={t} className="pill pill-theme" title="A theme of the stories">
                {t}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="scrim insp-list">
        <p className="lbl insp-list-lbl">
          <span>Linking stories</span>
          {articles.length > 0 && (
            <span>
              {articles.length} of {n}
            </span>
          )}
        </p>
        {entry.detailLoading && (
          <>
            <p className="insp-status">Fetching stories…</p>
            {[0, 1, 2].map((i) => (
              <div key={i} className="art" aria-hidden="true">
                <span className="skel" />
                <span className="skel short" />
              </div>
            ))}
          </>
        )}
        {entry.detailError && (
          <p className="insp-status">Couldn&apos;t load the stories for this link.</p>
        )}
        {detail && articles.length === 0 && (
          <p className="insp-status">No stories link these two in this window.</p>
        )}
        {articles.length > 0 && (
          <ul className="insp-stories" aria-label="Linking stories">
            {articles.map((a) => (
              <li key={a.id} className="art">
                {isWebUrl(a.sourceUrl) ? (
                  <a className="h" href={a.sourceUrl} target="_blank" rel="noopener noreferrer">
                    {a.title}
                  </a>
                ) : (
                  <span className="h">{a.title}</span>
                )}
                <div className="m">
                  <span>{a.sourceName}</span>
                  <span>{placeOf(a)}</span>
                  <span>{formatAgo(a.publishedAt, asOf)}</span>
                  <span className="sent" style={sentStyle(a.sentimentScore)}>
                    <span className="sr-only">Tone </span>
                    {formatScore(a.sentimentScore)}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div
        className="link-explain"
        data-testid="link-explain"
        aria-live="polite"
        aria-busy={explaining || undefined}
      >
        {explaining && <AiSkeleton />}
        {explanation?.ai ? (
          <div className="scrim insp-ai">
            <p>
              <span className="ai">AI</span>
              {explanation.text}
            </p>
          </div>
        ) : (
          <>
            {explanation && !explaining && <p className="insp-note">{explanation.text}</p>}
            <div>
              <button
                type="button"
                className="aurora-btn"
                disabled={explaining}
                onClick={onExplain}
              >
                <span className="ai">AI</span> {explaining ? "Explaining…" : "Explain this link"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
