"use client";

import { useCallback, useEffect, useState, type RefObject } from "react";

/**
 * Keeps focus in a region when a change removes the control that had it,
 * such as a place minimized or closed in the Stories tab. Call the returned
 * function in the same handler as the change, with the place whose pill
 * should take focus (an element with `data-place` set to its id). Once that
 * change renders, if focus was lost, it moves to that pill, or to the region
 * (give it `tabIndex={-1}`) when the pill is gone. Focus outside the region
 * is never touched.
 */
export function useKeepFocus(regionRef: RefObject<HTMLElement | null>) {
  // State, not a ref: the request commits with the change it belongs to, so an
  // earlier render's effects can't act on it before the control is gone.
  const [request, setRequest] = useState<{ placeId: string | null } | null>(null);

  const keepFocus = useCallback(
    (placeId: string | null) => {
      const region = regionRef.current;
      if (region && region.contains(document.activeElement)) setRequest({ placeId });
    },
    [regionRef],
  );

  useEffect(() => {
    const region = regionRef.current;
    if (!request || !region) return;
    const active = document.activeElement;
    if (active && active !== document.body && region.contains(active)) return; // focus survived
    const pill = Array.from(region.querySelectorAll<HTMLElement>("[data-place]")).find(
      (el) => el.dataset.place === request.placeId,
    );
    (pill ?? region).focus();
  }, [request, regionRef]);

  return keepFocus;
}
