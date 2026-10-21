"use client";

import { useLayoutEffect, useRef, type FocusEvent } from "react";

/**
 * Keeps a list's keyboard focus while its rows change under it (a new rank,
 * class or window): a focused row that is still listed keeps it, and one that
 * drops out hands it to the first row, or to the list itself (its box, which
 * needs tabIndex -1) when none are left, rather than to the page.
 *
 * `keys` are the rows' keys, each row carrying its key in `rowAttr` (e.g.
 * "data-link"). Spread `onFocus` and `onBlur` on the box, with `boxRef`.
 */
export function useRowFocus(keys: readonly string[], rowAttr: string) {
  const boxRef = useRef<HTMLDivElement>(null);
  // The row that had the focus, until the focus leaves the list on purpose.
  const focusedRow = useRef<string | null>(null);
  const rowSelector = `[${rowAttr}]`;
  const signature = keys.join("\n");

  // Layout effect: before anything else can move the focus that the row's
  // removal dropped on the page.
  useLayoutEffect(() => {
    const box = boxRef.current;
    const row = focusedRow.current;
    if (!box || row === null) return;
    const active = document.activeElement;
    if (active && active !== document.body) return; // still on its row, or elsewhere
    if (signature.split("\n").includes(row)) return; // listed: not ours to move
    (box.querySelector<HTMLElement>(rowSelector) ?? box).focus();
  }, [signature, rowSelector]);

  const onFocus = (e: FocusEvent<HTMLElement>) => {
    const row = e.target.closest<HTMLElement>(rowSelector)?.getAttribute(rowAttr);
    if (row) focusedRow.current = row;
  };
  // Left on purpose (another control, or a click on the globe) while the row
  // is still there: forget it. A row the list dropped is no longer connected.
  const onBlur = (e: FocusEvent<HTMLElement>) => {
    const target = e.target;
    setTimeout(() => {
      const box = boxRef.current;
      if (target.isConnected && !box?.contains(document.activeElement)) focusedRow.current = null;
    }, 0);
  };

  return { boxRef, onFocus, onBlur };
}
