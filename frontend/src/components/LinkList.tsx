"use client";

import { linkKey, linkPairLabel, type LinkRank } from "@/lib/links";
import type { CountryLink } from "@/types/news";

interface LinkListProps {
  /** The links the globe draws, in rank order. */
  links: readonly CountryLink[];
  rank: LinkRank;
  onOpen: (link: CountryLink) => void;
}

const stories = (n: number) => `${n} ${n === 1 ? "story" : "stories"}`;

/**
 * The links on the globe as a list, in the Inspect tab while nothing is open
 * there and Links is on: the way to open a link without pointing at its arc
 * (from the keyboard, and on a phone). Each opens as an arc's click does.
 */
export default function LinkList({ links, rank, onOpen }: LinkListProps) {
  if (links.length === 0) return null;
  return (
    <div className="scrim insp-list link-list" data-testid="link-list">
      <p className="lbl insp-list-lbl">
        <span>Links on the globe</span>
        <span>{rank === "lift" ? "Most surprising first" : "Most covered first"}</span>
      </p>
      <ul className="insp-stories" aria-label="Links on the globe">
        {links.map((link) => {
          const { short, long } = linkPairLabel(link);
          return (
            <li key={linkKey(link.a.iso, link.b.iso)}>
              <button
                type="button"
                className="art link-row"
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
    </div>
  );
}
