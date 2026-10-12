"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type RefObject,
} from "react";
import type { GlobePoint } from "@/types/news";

/** How long the pointer rests on a dot before its card shows. */
export const SHOW_DELAY_MS = 150;
/** How long the card waits for the pointer once it leaves the dot or the card. */
export const HIDE_GRACE_MS = 300;

export interface ShownCard {
  point: GlobePoint;
  /** When it showed (Date.now()), for its stories' ages. */
  shownAt: number;
}

/** The same dot: points are rebuilt each time the globe refetches. */
const samePlace = (a: GlobePoint | null | undefined, b: GlobePoint | null | undefined) =>
  !!a && !!b && a.lat === b.lat && a.lng === b.lng;

const NO_HOVER_QUERY = "(hover: none)";

function noHoverQuery(): MediaQueryList | null {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return null;
  return window.matchMedia(NO_HOVER_QUERY);
}

function subscribeNoHover(onChange: () => void) {
  const mql = noHoverQuery();
  if (!mql) return () => {};
  mql.addEventListener("change", onChange);
  return () => mql.removeEventListener("change", onChange);
}

/** A touch screen, which can't hover: the card shows on a tap instead (`(hover: none)`). */
export function useTouchOnly(): boolean {
  return useSyncExternalStore(
    subscribeNoHover,
    () => noHoverQuery()?.matches ?? false,
    () => false,
  );
}

/**
 * Which dot's hover card shows, and when.
 *
 * With a mouse, the card shows once the pointer has rested SHOW_DELAY_MS on
 * a dot, and stays while the pointer is on the dot or on the card (with a
 * HIDE_GRACE_MS grace to cross between them, so the card's buttons can be
 * reached). Escape, or a click on the dot (its panel opens), hides it until
 * the pointer leaves that dot.
 *
 * On a touch screen hovers are ignored: the first tap on a dot shows its
 * card, a second tap on it reports that its panel should open (`tap` returns
 * true), and a tap anywhere else hides it: off the dots on the globe
 * (`onEmptyTap`), or on the page outside `cardRef`'s card.
 *
 * When `points` change (a new window or topic) and the card's place is no
 * longer among them, the card goes.
 *
 * `focus` is the dot the preview dwells on: the hovered one, else the card's.
 */
export function useHoverCard(
  touch: boolean,
  cardRef?: RefObject<HTMLElement | null>,
  points?: readonly GlobePoint[],
) {
  const [card, setCard] = useState<ShownCard | null>(null);
  const [hovered, setHovered] = useState<GlobePoint | null>(null);
  const [dismissed, setDismissed] = useState<GlobePoint | null>(null);
  // The same state for handlers and timers, which can't wait for a render.
  const live = useRef({
    card: null as ShownCard | null,
    hovered: null as GlobePoint | null,
    dismissed: null as GlobePoint | null,
    overCard: false,
  });
  const showTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const putCard = useCallback((next: ShownCard | null) => {
    live.current.card = next;
    setCard(next);
  }, []);

  const hideNow = useCallback(() => {
    clearTimeout(showTimer.current);
    clearTimeout(hideTimer.current);
    live.current.overCard = false;
    putCard(null);
  }, [putCard]);

  const hideSoon = useCallback(() => {
    clearTimeout(hideTimer.current);
    hideTimer.current = setTimeout(() => {
      if (!live.current.overCard) hideNow();
    }, HIDE_GRACE_MS);
  }, [hideNow]);

  const setDismissedPoint = useCallback((point: GlobePoint | null) => {
    live.current.dismissed = point;
    setDismissed(point);
  }, []);

  const onPointHover = useCallback(
    (point: GlobePoint | null) => {
      if (touch) return;
      live.current.hovered = point;
      setHovered(point);
      clearTimeout(showTimer.current);
      if (live.current.dismissed && !samePlace(point, live.current.dismissed)) {
        setDismissedPoint(null);
      }
      if (!point) {
        if (live.current.card) hideSoon();
        return;
      }
      clearTimeout(hideTimer.current);
      if (live.current.dismissed) return; // still on the dot that was dismissed
      const shown = live.current.card;
      if (shown && samePlace(shown.point, point)) {
        if (shown.point !== point) putCard({ ...shown, point }); // its point was refreshed
        return;
      }
      showTimer.current = setTimeout(() => putCard({ point, shownAt: Date.now() }), SHOW_DELAY_MS);
    },
    [touch, hideSoon, putCard, setDismissedPoint],
  );

  /** Escape, or a click on the dot: hide until the pointer leaves the dot. */
  const dismiss = useCallback(() => {
    setDismissedPoint(live.current.hovered ?? live.current.card?.point ?? null);
    hideNow();
  }, [hideNow, setDismissedPoint]);

  const onCardEnter = useCallback(() => {
    live.current.overCard = true;
    clearTimeout(hideTimer.current);
  }, []);

  const onCardLeave = useCallback(() => {
    live.current.overCard = false;
    // A finger lifting off the card is no reason to hide it.
    if (!touch) hideSoon();
  }, [touch, hideSoon]);

  /** A tap on a dot (touch): true when it should open the dot's panel. */
  const tap = useCallback(
    (point: GlobePoint): boolean => {
      if (samePlace(live.current.card?.point, point)) {
        hideNow();
        return true;
      }
      clearTimeout(hideTimer.current);
      putCard({ point, shownAt: Date.now() });
      return false;
    },
    [hideNow, putCard],
  );

  /** A tap on the globe off the dots (touch) hides the card. */
  const onEmptyTap = useCallback(() => {
    if (touch) hideNow();
  }, [touch, hideNow]);

  useEffect(() => {
    if (!card) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") dismiss();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [card, dismiss]);

  // Touch: a tap on the page outside the card hides it. The globe's own taps
  // come through tap and onEmptyTap, after globe.gl has found the dot.
  useEffect(() => {
    if (!touch || !card) return;
    const onDown = (e: PointerEvent) => {
      const target = e.target instanceof Element ? e.target : null;
      if (!target || cardRef?.current?.contains(target)) return;
      if (target.closest('[data-testid="globe"]')) return;
      hideNow();
    };
    document.addEventListener("pointerdown", onDown, true);
    return () => document.removeEventListener("pointerdown", onDown, true);
  }, [touch, card, cardRef, hideNow]);

  // New dots without the card's place: its stories aren't on the globe now.
  // The page already shows no card for a place that isn't a dot; the state
  // follows on the next tick (a timer, as effects mustn't set state directly).
  useEffect(() => {
    const shown = live.current.card;
    if (!points || !shown || points.some((p) => samePlace(p, shown.point))) return;
    const timer = setTimeout(hideNow, 0);
    return () => clearTimeout(timer);
  }, [points, hideNow]);

  useEffect(
    () => () => {
      clearTimeout(showTimer.current);
      clearTimeout(hideTimer.current);
    },
    [],
  );

  const hoverFocus = hovered && !samePlace(hovered, dismissed) ? hovered : null;
  return {
    card,
    focus: hoverFocus ?? card?.point ?? null,
    onPointHover,
    onCardEnter,
    onCardLeave,
    dismiss,
    tap,
    onEmptyTap,
  };
}
