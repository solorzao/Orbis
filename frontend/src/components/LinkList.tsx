"use client";

import { useId, useLayoutEffect, useRef, type FocusEvent } from "react";
import { linkKey, linkPairLabel, type LinkRank } from "@/lib/links";
import type { CountryLink } from "@/types/news";

interface LinkListProps {
  /** The links the globe draws, in rank order. */
  links: readonly CountryLink[];
  rank: LinkRank;
  /** Why there are none (the Links status), or null while they load. */
  status: string | null;
  onOpen: (link: CountryLink) => void;
}

const stories = (n: number) => `${n} ${n === 1 ? "story" : "stories"}`;

/**
 * The links on the globe as a list, in the Inspect tab while nothing is open
 * there and Links is on: the way to open a link without pointing at its arc
 * (from the keyboard, and on a phone). Each opens as an arc's click does.
 *
 * The links change under the focus (a new rank, or a replay's window): a
 * focused row that is still listed keeps it, and one that drops out hands it
 * to the first row, or to the list when none are left, rather than the page.
 */
export default function LinkList({ links, rank, status, onOpen }: LinkListProps) {
  const labelId = useId();
  const boxRef = useRef<HTMLDivElement>(null);
  // The row that had the focus, until the focus leaves the list on purpose.
  const focusedRow = useRef<string | null>(null);

  // Layout effect: before anything else can move the focus that the row's
  // removal dropped on the page.
  useLayoutEffect(() => {
    const box = boxRef.current;
    const row = focusedRow.current;
    if (!box || row === null) return;
    const active = document.activeElement;
    if (active && active !== document.body) return; // still on its row, or elsewhere
    if (links.some((l) => linkKey(l.a.iso, l.b.iso) === row)) return; // listed: not ours to move
    (box.querySelector<HTMLElement>(".link-row") ?? box).focus();
  }, [links]);

  const onFocus = (e: FocusEvent<HTMLDivElement>) => {
    const row = e.target.closest<HTMLElement>("[data-link]")?.dataset.link;
    if (row) focusedRow.current = row;
  };
  // Left on purpose (another control, or a click on the globe) while the row
  // is still there: forget it. A row the list dropped is no longer connected.
  const onBlur = (e: FocusEvent<HTMLDivElement>) => {
    const target = e.target;
    setTimeout(() => {
      const box = boxRef.current;
      if (target.isConnected && !box?.contains(document.activeElement)) focusedRow.current = null;
    }, 0);
  };

  return (
    <div
      ref={boxRef}
      className="scrim insp-list link-list"
      data-testid="link-list"
      role="group"
      aria-labelledby={labelId}
      tabIndex={-1}
      onFocus={onFocus}
      onBlur={onBlur}
    >
      <p className="lbl insp-list-lbl">
        <span id={labelId}>Links on the globe</span>
        {links.length > 0 && (
          <span>{rank === "lift" ? "Most surprising first" : "Most covered first"}</span>
        )}
      </p>
      {links.length === 0 ? (
        <p className="insp-status">{status ?? "Loading links…"}</p>
      ) : (
        <ul className="insp-stories" aria-label="Links on the globe">
          {links.map((link) => {
            const { short, long } = linkPairLabel(link);
            const key = linkKey(link.a.iso, link.b.iso);
            return (
              <li key={key}>
                <button
                  type="button"
                  className="art link-row"
                  data-link={key}
                  aria-label={`${long}, ${short}, ${stories(link.n)}`}
                  onClick={() => onOpen(link)}
                >
                  <span className="h">{long}</span>
                  <span className="m">
                    <span>{short}</span>
                    <span>{stories(link.n)}</span>
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
