"use client";

import { useCallback, useRef } from "react";
import { LINK_EXPLAIN_FAILED, explainLink, isExplainFallback } from "@/lib/api";
import type { LinkEntry } from "@/types/news";

/**
 * Explain this link: Claude's words (with the AI badge), or the message the
 * server sent instead (paused, failed, too few stories) as plain text. One
 * request per link at a time, however fast the clicks: an in-flight flag in a
 * ref, which two clicks in one task (before React re-renders, so before
 * `entry.explaining` is true) both see.
 */
export function useLinkExplain(
  updateLink: (linkId: string, updates: Partial<LinkEntry>) => void,
): (entry: LinkEntry) => Promise<void> {
  const inFlight = useRef(new Set<string>());

  return useCallback(
    async (entry: LinkEntry) => {
      const { linkId } = entry;
      if (inFlight.current.has(linkId)) return;
      inFlight.current.add(linkId);
      updateLink(linkId, { explaining: true });
      try {
        const { text } = await explainLink({
          a: entry.link.a.iso,
          b: entry.link.b.iso,
          query: entry.query,
        });
        updateLink(linkId, {
          explaining: false,
          explanation: { text, ai: !isExplainFallback(text) },
        });
      } catch {
        updateLink(linkId, {
          explaining: false,
          explanation: { text: LINK_EXPLAIN_FAILED, ai: false },
        });
      } finally {
        inFlight.current.delete(linkId);
      }
    },
    [updateLink],
  );
}
