"use client";

import { useEffect, useId, useRef, type KeyboardEvent } from "react";
import { MAX_PINS } from "@/lib/board";

interface BoardMergePromptProps {
  /** Pins the link shares. */
  shared: number;
  /** Of them, the ones the board lacks. */
  fresh: number;
  /** Of those, the ones there is room for. */
  fit: number;
  onAdd: () => void;
  onKeep: () => void;
}

const pins = (n: number) => `${n} ${n === 1 ? "pin" : "pins"}`;

/**
 * Before a share link's pins join a board that has pins of its own: a modal
 * dialog asking whether to add them. It keeps the focus inside, starts on
 * its first button, and Escape keeps the board as it is.
 */
export default function BoardMergePrompt({
  shared,
  fresh,
  fit,
  onAdd,
  onKeep,
}: BoardMergePromptProps) {
  const id = useId();
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    dialogRef.current?.querySelector("button")?.focus();
  }, []);

  const description =
    fit === 0
      ? `This link shares ${pins(shared)}. Your board is full (${MAX_PINS} pins), so none fit.`
      : `This link shares ${pins(shared)}. ${fresh} aren't on your board yet` +
        (fit < fresh ? `; ${fit} fit, as a board holds ${MAX_PINS}.` : ".");

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      onKeep();
      return;
    }
    if (e.key !== "Tab") return;
    const buttons = Array.from(dialogRef.current?.querySelectorAll("button") ?? []);
    const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const next = e.shiftKey ? (at <= 0 ? buttons.length - 1 : at - 1) : (at + 1) % buttons.length;
    e.preventDefault();
    buttons[next]?.focus();
  };

  return (
    <div className="board-scrim">
      <div
        ref={dialogRef}
        className="glass board-prompt"
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        aria-describedby={`${id}-text`}
        data-testid="board-merge"
        onKeyDown={onKeyDown}
      >
        <h2 id={`${id}-title`}>Add the shared pins to your board?</h2>
        <p id={`${id}-text`}>{description}</p>
        <div className="board-prompt-actions">
          {fit > 0 && (
            <button type="button" className="aurora-btn" onClick={onAdd}>
              Add to my board
            </button>
          )}
          <button type="button" className="pill" onClick={onKeep}>
            Keep my board
          </button>
        </div>
      </div>
    </div>
  );
}
