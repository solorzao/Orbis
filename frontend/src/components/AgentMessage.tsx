"use client";

import { memo, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import {
  cleanLabel,
  type AgentMessage as AgentMessageType,
  type Citation,
  type GlobeAction,
} from "@/hooks/useAgent";

/** The quiet tool line while an answer streams: what each retrieval tool is doing. */
const TOOL_LINES: Record<string, string> = {
  semantic_search: "searching articles",
  keyword_search: "searching headlines",
  graph_traverse: "following connections",
  entity_lookup: "looking up names",
  trending_topics: "checking trends",
  read_article: "reading articles",
};

/** "Searching articles, checking trends…", or "Thinking…" before the plan. */
export function toolLine(tools: readonly string[]): string {
  const doing = [...new Set(tools.map((t) => TOOL_LINES[t] ?? "searching"))].join(", ");
  return doing ? `${doing[0].toUpperCase()}${doing.slice(1)}…` : "Thinking…";
}

const CITE_HREF = "#cite-";
const NO_IMAGES = ["img"];

/** "[4]" becomes a link to #cite-4 so the `a` renderer can draw it as a pill (not "[4](url)" or "[4]: url"). */
function linkCitations(markdown: string): string {
  return markdown.replace(/\[(\d{1,3})\](?![(:])/g, `[$1](${CITE_HREF}$1)`);
}

/** The citation an answer's "[n]" points at: by its index, or by position for older answers. */
function citationFor(citations: readonly Citation[], n: number): Citation | undefined {
  if (citations.some((c) => c.index !== undefined)) return citations.find((c) => c.index === n);
  return citations[n - 1];
}

const numberOf = (c: Citation, i: number) => c.index ?? i + 1;

function sourceLine(c: Citation): string {
  return c.source_name ? `${c.source_name}: ${c.title}` : c.title;
}

interface AgentMessageProps {
  message: AgentMessageType;
  /** While this answer streams: the tools at work, for the tool line. */
  activeTools?: readonly string[];
  onCitationClick?: (citation: Citation) => void;
  onFlyTo?: (action: GlobeAction) => void;
  /** Opens the Inspect tab at an action's place, or null when the globe has no dot there. */
  showStoriesFor?: (action: GlobeAction) => (() => void) | null;
  /** Show links for an answer's places (Links' state and how to turn it on), or null. */
  showLinksFor?: (actions: GlobeAction[]) => LinksAction | null;
}

/** The Show links pill: pressed (and inert) while Links is on. */
export interface LinksAction {
  on: boolean;
  turnOn: () => void;
}

/**
 * One message in the co-pilot console (mockup .msg, lines 336-350): the
 * question as a bubble; the answer as prose with numbered citation pills,
 * then its sources and the actions it suggests. Memoised (see the export):
 * while an answer streams, only it re-renders, not the ones before it.
 */
function AgentMessage({
  message,
  activeTools = [],
  onCitationClick,
  onFlyTo,
  showStoriesFor,
  showLinksFor,
}: AgentMessageProps) {
  if (message.role === "user") return <div className="msg user">{message.content}</div>;

  const citations = message.citations ?? [];
  const streaming = message.status === "streaming";

  const cite = (n: number, key?: string): ReactNode => {
    const citation = citationFor(citations, n);
    if (!citation) {
      return (
        <span key={key} className="cite">
          {n}
        </span>
      );
    }
    return (
      <button
        key={key}
        type="button"
        className="cite"
        aria-label={`Source ${n}`}
        title={sourceLine(citation)}
        onClick={() => onCitationClick?.(citation)}
      >
        {n}
      </button>
    );
  };

  const components: Components = {
    a: ({ href, children }) =>
      href?.startsWith(CITE_HREF) ? (
        cite(Number(href.slice(CITE_HREF.length)))
      ) : (
        <a href={href} target="_blank" rel="noopener noreferrer">
          {children}
        </a>
      ),
  };

  // Sources in the order cited, one row per number.
  const sources = citations.filter(
    (c, i) => citations.findIndex((d, j) => numberOf(d, j) === numberOf(c, i)) === i,
  );

  const actions = streaming ? [] : (message.globeActions ?? []).slice(0, 3);
  const openStories = actions.length > 0 ? (showStoriesFor?.(actions[0]) ?? null) : null;
  const showLinks = actions.length > 0 ? (showLinksFor?.(actions) ?? null) : null;

  return (
    <div className="msg bot" aria-busy={streaming}>
      {streaming && (
        <p className="tools">
          <i aria-hidden="true" />
          {toolLine(activeTools)}
        </p>
      )}

      {message.content && (
        // No images: a model-written one would load from wherever the answer points.
        <ReactMarkdown components={components} disallowedElements={NO_IMAGES}>
          {linkCitations(message.content)}
        </ReactMarkdown>
      )}

      {sources.length > 0 && (
        <div className="sources" role="group" aria-label="Sources">
          {sources.map((c) => {
            const n = numberOf(c, citations.indexOf(c));
            return (
              <button
                key={`${n}-${c.url}`}
                type="button"
                title={sourceLine(c)}
                onClick={() => onCitationClick?.(c)}
              >
                <span className="cite">{n}</span>
                <span>{sourceLine(c)}</span>
              </button>
            );
          })}
        </div>
      )}

      {actions.length > 0 && (
        <div className="actions" role="group" aria-label="Suggested actions">
          {actions.map((action, i) => {
            const label = cleanLabel(action.label);
            return (
              <button
                key={`${i}-${action.lat}-${action.lng}`}
                type="button"
                className="pill"
                onClick={() => onFlyTo?.(action)}
              >
                {label ? `Fly to ${label}` : "Fly there"}
              </button>
            );
          })}
          {openStories && (
            <button type="button" className="pill" onClick={openStories}>
              Show stories here
            </button>
          )}
          {showLinks && (
            // Stays once Links is on, pressed: so the focus has somewhere to stay.
            <button
              type="button"
              className="pill"
              aria-pressed={showLinks.on}
              aria-disabled={showLinks.on || undefined}
              onClick={showLinks.on ? undefined : showLinks.turnOn}
            >
              Show links
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// useAgent keeps each finished message's object, and the page's handlers are
// stable, so a token re-renders the streaming answer only.
export default memo(AgentMessage);
