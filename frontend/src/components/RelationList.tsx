"use client";

import { useId, type CSSProperties } from "react";
import {
  relationKey,
  relationLensLabel,
  relationPairLabel,
  relationWords,
  reportedEvents,
  type Relation,
  type RelationLens,
} from "@/lib/relations";
import { useRowFocus } from "@/hooks/useRowFocus";

interface RelationListProps {
  /** The relations the globe draws, strongest first. */
  relations: readonly Relation[];
  /** The lens they cover, or null while they load. */
  lens: RelationLens | null;
  /** Why there are none (the Relations status), or null while they load. */
  status: string | null;
  onOpen: (relation: Relation) => void;
  /** A row took the focus (its arc is labelled, as on hover), or null when it left. */
  onFocusRelation: (relation: Relation | null) => void;
}

const sideColor = (rel: Relation) =>
  ({ "--c": `var(--arc-relation-${rel.kind})` }) as CSSProperties;

/**
 * The relations on the globe as a list, in the Inspect tab while nothing is
 * open there and Relations is on: every arc named in words (decision 6), and
 * the way to open one without pointing at its arc. A row with the focus
 * labels its arc on the globe, as hovering does. Its focus keeps its place
 * while the relations change (useRowFocus), as the link list's does.
 */
export default function RelationList({
  relations,
  lens,
  status,
  onOpen,
  onFocusRelation,
}: RelationListProps) {
  const labelId = useId();
  const { boxRef, onFocus, onBlur } = useRowFocus(
    relations.map((r) => relationKey(r.a.iso, r.b.iso)),
    "data-relation",
  );

  return (
    <div
      ref={boxRef}
      className="scrim insp-list link-list relation-list"
      data-testid="relation-list"
      role="group"
      aria-labelledby={labelId}
      tabIndex={-1}
      onFocus={onFocus}
      onBlur={onBlur}
    >
      <p className="lbl insp-list-lbl">
        <span id={labelId}>{lens ? relationLensLabel(lens) : "Relations · last 7 days"}</span>
      </p>
      {relations.length === 0 ? (
        <p className="insp-status">{status ?? "Loading relations…"}</p>
      ) : (
        <ul className="insp-stories" aria-label="Relations on the globe">
          {relations.map((rel) => {
            const key = relationKey(rel.a.iso, rel.b.iso);
            const { long } = relationPairLabel(rel);
            const words = relationWords(rel);
            return (
              <li key={key}>
                <button
                  type="button"
                  className="art link-row"
                  data-relation={key}
                  aria-label={`${long}: ${reportedEvents(rel.n)}, ${words}`}
                  onClick={() => onOpen(rel)}
                  onFocus={() => onFocusRelation(rel)}
                  onBlur={() => onFocusRelation(null)}
                >
                  <span className="h">{long}</span>
                  <span className="m">
                    <span>{reportedEvents(rel.n)}</span>
                    <span className="art-tag" style={sideColor(rel)}>
                      {words}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
