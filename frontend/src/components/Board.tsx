"use client";

import {
  memo as memoComponent,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from "react";
import { isWebUrl } from "@/hooks/useAgent";
import { keyMove, pinKindLabel, positionWords, shareUrl, type Pin } from "@/lib/board";
import { EDGE_LEGEND, layoutEdges, pinEdges, type BoardEdge, type CardBox } from "@/lib/boardEdges";
import { memoParts, type BoardMemo } from "@/lib/boardApi";
import { EXPORT_FILENAME, boardMarkdown } from "@/lib/boardExport";

/**
 * A card's box on the canvas (mockup .pin: 214px wide; tall enough for its
 * kicker and two lines of title, as .pin-card's min-height), and the
 * canvas's inner margin.
 */
const CARD_W = 214;
const CARD_H = 84;
const PAD = 16;

interface BoardProps {
  /** The split view from 1180px (a canvas), or the sheet's list below. */
  variant: "split" | "sheet";
  pins: readonly Pin[];
  /** The board's edges (boardEdges): the server's and close in time. */
  edges: readonly BoardEdge[];
  /** False: the server couldn't check co-coverage this time (the legend says so). */
  coCoverageChecked: boolean;
  /** The edges couldn't be had at all (a 429, an outage): said in the legend's place. */
  edgesFailed?: boolean;
  memo: BoardMemo | null;
  analyzing: boolean;
  onAnalyze: () => void;
  onDismissMemo: () => void;
  onMove: (item: string, x: number, y: number) => void;
  onRemove: (item: string) => void;
  onClose: () => void;
}

const where = (p: Pin) =>
  p.snapshot.place && p.snapshot.place !== p.snapshot.title ? `, ${p.snapshot.place}` : "";

/** "1. Story, Paris, France": a pin's number, kind and place. */
const pinKicker = (p: Pin, i: number) => `${i + 1}. ${pinKindLabel(p.item)}${where(p)}`;
const pinName = (p: Pin, i: number) => `${pinKicker(p, i)}: ${p.snapshot.title}`;

const plural = (n: number) => `${n} ${n === 1 ? "pin" : "pins"}`;

const UNAVAILABLE = "Connections unavailable right now";

/** A pin's title: a link to its story when it has a web link. */
function PinTitle({ pin }: { pin: Pin }) {
  const { title, url } = pin.snapshot;
  return isWebUrl(url) ? (
    <a className="h" href={url} target="_blank" rel="noopener noreferrer">
      {title}
    </a>
  ) : (
    <p className="h">{title}</p>
  );
}

function RemoveButton({ pin, i, onRemove }: { pin: Pin; i: number; onRemove: () => void }) {
  return (
    <button
      type="button"
      className="iconbtn pin-x"
      aria-label={`Remove pin ${i + 1}: ${pin.snapshot.title}`}
      title="Remove from the board"
      onClick={onRemove}
    >
      <svg width="9" height="9" viewBox="0 0 12 12" aria-hidden="true">
        <path
          d="M2 2l8 8M10 2l-8 8"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
        />
      </svg>
    </button>
  );
}

/** The analysis memo (mockup .memo): its sections, citing pins by number, or a message. */
function MemoPanel({
  memo,
  analyzing,
  pins,
  onCite,
  onDismiss,
}: {
  memo: BoardMemo | null;
  analyzing: boolean;
  pins: readonly Pin[];
  onCite: (item: string) => void;
  onDismiss: () => void;
}) {
  const titles = new Map(pins.map((p) => [p.item, p.snapshot.title]));
  const cite = (n: number, key: string): ReactNode => {
    const item = memo?.citations.find((c) => c.n === n)?.item ?? memo?.items[n - 1];
    const title = item ? titles.get(item) : undefined;
    if (!item || title === undefined) return `[${n}]`;
    return (
      <button
        key={key}
        type="button"
        className="cite"
        aria-label={`Pin ${n}: ${title}`}
        onClick={() => onCite(item)}
      >
        {n}
      </button>
    );
  };
  return (
    <section
      className="memo"
      aria-label="Analysis memo"
      aria-busy={analyzing || undefined}
      data-testid="board-memo"
    >
      <div className="memo-head">
        <span className="ai">AI</span>
        <span className="muted">Analysis memo</span>
        <button
          type="button"
          className="iconbtn memo-x"
          aria-label="Close memo"
          onClick={onDismiss}
        >
          <svg width="9" height="9" viewBox="0 0 12 12" aria-hidden="true">
            <path
              d="M2 2l8 8M10 2l-8 8"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
            />
          </svg>
        </button>
      </div>
      {analyzing ? (
        <div aria-hidden="true" className="memo-skel">
          <span className="skel" />
          <span className="skel" />
          <span className="skel short" />
        </div>
      ) : memo?.message ? (
        <p className="memo-msg">{memo.message}</p>
      ) : (
        memo?.sections.map((s) => (
          <div key={s.heading} className="memo-sec">
            <h3>{s.heading}</h3>
            <p>
              {memoParts(s.text).map((part, i) =>
                "n" in part ? cite(part.n, `${s.heading}-${i}`) : part.text,
              )}
            </p>
          </div>
        ))
      )}
    </section>
  );
}

/** What a card does, the same functions for the board's life (so a card re-renders only when it changes). */
interface CardHandlers {
  key: (e: KeyboardEvent<HTMLElement>, pin: Pin, index: number) => void;
  down: (e: PointerEvent<HTMLElement>, pin: Pin) => void;
  move: (e: PointerEvent<HTMLElement>) => void;
  up: (e: PointerEvent<HTMLElement>) => void;
  remove: (index: number) => void;
  ref: (item: string, el: HTMLElement | null) => void;
}

/**
 * A pin's card on the canvas (mockup .pin): its number, kind and place, and
 * its title; a focusable group that the arrow keys and the pointer move.
 * Memoised: while one card is dragged, the others keep their render.
 */
const PinCard = memoComponent(function PinCard({
  pin,
  index,
  left,
  top,
  x,
  y,
  dragging,
  hintId,
  handlers,
}: {
  pin: Pin;
  index: number;
  left: number;
  top: number;
  /** Where it is on the board now (0-1), for data-x/data-y. */
  x: number;
  y: number;
  dragging: boolean;
  hintId: string;
  handlers: CardHandlers;
}) {
  return (
    <li
      className="pin"
      style={{ left, top }}
      data-item={pin.item}
      data-x={x.toFixed(2)}
      data-y={y.toFixed(2)}
    >
      <div
        ref={(el) => handlers.ref(pin.item, el)}
        className="pin-card"
        role="group"
        tabIndex={0}
        aria-label={pinName(pin, index)}
        aria-describedby={hintId}
        data-dragging={dragging || undefined}
        onKeyDown={(e) => handlers.key(e, pin, index)}
        onPointerDown={(e) => handlers.down(e, pin)}
        onPointerMove={handlers.move}
        onPointerUp={handlers.up}
        onPointerCancel={handlers.up}
      >
        <div className="k">
          <span>{pinKicker(pin, index)}</span>
        </div>
        <PinTitle pin={pin} />
      </div>
      <RemoveButton pin={pin} i={index} onRemove={() => handlers.remove(index)} />
    </li>
  );
});

/**
 * The investigation board (mockup section.board): from 1180px a split view
 * on the left with the globe mirroring it on the right, its pins as cards on
 * a canvas with typed edges between them; below, the sheet's list of pins,
 * each with its edges. Cards drag with the pointer and move with the arrow
 * keys; Analyze asks for a cited memo; Export downloads the board as
 * Markdown; Share link copies a link to its pins' ids. Escape closes it.
 */
export default function Board({
  variant,
  pins,
  edges,
  coCoverageChecked,
  edgesFailed = false,
  memo,
  analyzing,
  onAnalyze,
  onDismissMemo,
  onMove,
  onRemove,
  onClose,
}: BoardProps) {
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const closeRef = useRef<HTMLButtonElement>(null);
  const fieldRef = useRef<HTMLDivElement>(null);
  const shareRef = useRef<HTMLInputElement>(null);
  const pinRefs = useRef(new Map<string, HTMLElement>());
  const [size, setSize] = useState({ w: 0, h: 0 });
  // A card being dragged, where it is now; committed when it is let go.
  const [drag, setDrag] = useState<{ item: string; x: number; y: number } | null>(null);
  const dragStart = useRef<{ item: string; cx: number; cy: number; x: number; y: number } | null>(
    null,
  );
  const [note, setNote] = useState("");
  // The share link last made, for the pins it was made of.
  const [shared, setShared] = useState<{ url: string; copied: boolean; items: string } | null>(
    null,
  );

  // It opens on its Close button (mockup openBoard).
  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  // The canvas's size: the cards spread over it, and keep their places as it resizes.
  useLayoutEffect(() => {
    const field = fieldRef.current;
    if (!field || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() =>
      setSize({ w: field.clientWidth, h: field.clientHeight }),
    );
    observer.observe(field);
    return () => observer.disconnect();
  }, []);

  // The clipboard refused: the link is in the box, selected, to copy by hand.
  useEffect(() => {
    if (shared && !shared.copied) {
      shareRef.current?.focus();
      shareRef.current?.select();
    }
  }, [shared]);

  // A removed pin's button goes with it: the focus moves on to the next card
  // (else the previous one, else Close) once the board has it gone.
  const focusAfter = useRef<{ item: string | null } | null>(null);
  useEffect(() => {
    const after = focusAfter.current;
    if (!after) return;
    focusAfter.current = null;
    const next = after.item ? pinRefs.current.get(after.item) : undefined;
    (next ?? closeRef.current)?.focus();
  }, [pins]);
  const remove = (i: number) => {
    focusAfter.current = { item: pins[i + 1]?.item ?? pins[i - 1]?.item ?? null };
    onRemove(pins[i].item);
  };

  const spanX = Math.max(1, size.w - CARD_W - 2 * PAD);
  const spanY = Math.max(1, size.h - CARD_H - 2 * PAD);
  const placed = (p: Pin) => (drag?.item === p.item ? drag : p);
  // Each card's box on the canvas (where a drag has it now), and its centre for the edges.
  const { centres, boxes } = useMemo(() => {
    const centres = new Map<string, { x: number; y: number }>();
    const boxes: CardBox[] = [];
    for (const p of pins) {
      const { x, y } = drag?.item === p.item ? drag : p;
      const box = { x: PAD + x * spanX, y: PAD + y * spanY, w: CARD_W, h: CARD_H };
      boxes.push(box);
      centres.set(p.item, { x: box.x + CARD_W / 2, y: box.y + CARD_H / 2 });
    }
    return { centres, boxes };
  }, [pins, drag, spanX, spanY]);
  const laid = useMemo(
    () => (variant === "split" ? layoutEdges(centres, edges, boxes) : []),
    [variant, centres, boxes, edges],
  );
  const byPin = useMemo(() => pinEdges(pins, edges), [pins, edges]);
  const number = new Map(pins.map((p, i) => [p.item, i + 1]));

  const focusPin = (item: string) => pinRefs.current.get(item)?.focus();

  const onCardKey = (e: KeyboardEvent<HTMLElement>, p: Pin, i: number) => {
    const next = keyMove(p, e.key, e.shiftKey);
    if (!next) return;
    e.preventDefault();
    onMove(p.item, next.x, next.y);
    setNote(`Pin ${i + 1} moved: ${positionWords(next)}`);
  };

  const dragTo = (e: PointerEvent<HTMLElement>) => {
    const start = dragStart.current!;
    const clamp = (v: number) => Math.min(1, Math.max(0, v));
    return {
      item: start.item,
      x: clamp(start.x + (e.clientX - start.cx) / spanX),
      y: clamp(start.y + (e.clientY - start.cy) / spanY),
    };
  };
  const onPointerDown = (e: PointerEvent<HTMLElement>, p: Pin) => {
    if (e.button !== 0 || (e.target as HTMLElement).closest("a, button")) return;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    dragStart.current = { item: p.item, cx: e.clientX, cy: e.clientY, x: p.x, y: p.y };
  };
  const onPointerMove = (e: PointerEvent<HTMLElement>) => {
    if (dragStart.current) setDrag(dragTo(e));
  };
  const onPointerUp = (e: PointerEvent<HTMLElement>) => {
    if (!dragStart.current) return;
    const end = dragTo(e);
    const { x, y } = dragStart.current;
    dragStart.current = null;
    setDrag(null);
    if (end.x !== x || end.y !== y) onMove(end.item, end.x, end.y);
  };
  // The cards' handlers, stable for the board's life, each calling this
  // render's (which read its spans and pins): a card's props change only when
  // the card itself does.
  const latest = useRef({ onCardKey, onPointerDown, onPointerMove, onPointerUp, remove });
  useLayoutEffect(() => {
    latest.current = { onCardKey, onPointerDown, onPointerMove, onPointerUp, remove };
  });
  const handlers = useMemo<CardHandlers>(
    () => ({
      key: (e, pin, index) => latest.current.onCardKey(e, pin, index),
      down: (e, pin) => latest.current.onPointerDown(e, pin),
      move: (e) => latest.current.onPointerMove(e),
      up: (e) => latest.current.onPointerUp(e),
      remove: (index) => latest.current.remove(index),
      // Each card's (or row's) element, for a citation chip or a removal to focus.
      ref: (item, el) => {
        if (el) pinRefs.current.set(item, el);
        else pinRefs.current.delete(item);
      },
    }),
    [],
  );

  const exportBoard = () => {
    const text = boardMarkdown({ pins, edges, memo, now: Date.now() });
    const href = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = href;
    a.download = EXPORT_FILENAME;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(href), 1000);
    setNote(`Downloaded ${EXPORT_FILENAME}.`);
  };

  const items = pins.map((p) => p.item).join("\n");
  const share = async () => {
    const url = shareUrl(
      window.location.href,
      pins.map((p) => p.item),
    );
    try {
      await navigator.clipboard.writeText(url);
      setShared({ url, copied: true, items });
      setNote("Link copied.");
    } catch {
      setShared({ url, copied: false, items });
      setNote("Copy the link from the box.");
    }
  };

  const titleId = `${uid}-title`;
  const count = `${plural(pins.length)}, mirrored on the globe`;
  const memoShown = memo !== null || analyzing;
  const memoNote = analyzing ? "" : memo ? (memo.message ?? "The analysis memo is ready.") : "";

  const actions = (
    <>
      <button
        type="button"
        className="aurora-btn board-analyze"
        aria-disabled={analyzing || undefined}
        onClick={() => {
          if (!analyzing) onAnalyze();
        }}
      >
        {analyzing ? "Analyzing…" : "Analyze"}
      </button>
      <button type="button" className="pill" onClick={exportBoard}>
        Export
      </button>
      <button type="button" className="pill" onClick={share}>
        Share link
      </button>
    </>
  );
  const close = (
    <button
      ref={closeRef}
      type="button"
      className="iconbtn"
      aria-label="Close board"
      onClick={onClose}
    >
      <svg width="11" height="11" viewBox="0 0 12 12" aria-hidden="true">
        <path
          d="M2 2l8 8M10 2l-8 8"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinecap="round"
        />
      </svg>
    </button>
  );
  // Pins added or removed since: that link would share the old ones.
  const shareRow = shared && shared.items === items && (
    <label className="board-share">
      <span className="lbl">{shared.copied ? "Copied" : "Copy this link"}</span>
      <input ref={shareRef} readOnly value={shared.url} aria-label="Share link" />
    </label>
  );
  const memoPanel = memoShown && (
    <MemoPanel
      memo={memo}
      analyzing={analyzing}
      pins={pins}
      onCite={focusPin}
      onDismiss={onDismissMemo}
    />
  );
  const empty = pins.length === 0 && (
    <p className="board-empty">
      Nothing pinned yet. Pin places, stories, links, threads and people from their panels.
    </p>
  );
  const announcer = (
    <p className="sr-only" aria-live="polite" data-testid="board-announcer">
      <span>{note}</span> <span>{memoNote}</span>
    </p>
  );
  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      onClose();
    }
  };

  if (variant === "sheet") {
    return (
      <section
        className="board-sheet"
        aria-labelledby={titleId}
        data-testid="board-list"
        data-edges={edges.length}
        onKeyDown={onKeyDown}
      >
        <div className="board-sheet-head">
          <div className="min-w-0">
            <h2 id={titleId}>Investigation board</h2>
            <p className="sub">{count}</p>
          </div>
          {close}
        </div>
        <div className="board-actions">{actions}</div>
        {shareRow}
        {memoPanel}
        {empty}
        {pins.length > 0 && (
          <ol className="board-list" aria-label="Pins">
            {pins.map((p, i) => {
              const own = byPin.get(p.item) ?? [];
              return (
                <li
                  key={p.item}
                  ref={(el) => handlers.ref(p.item, el)}
                  className="board-row"
                  tabIndex={-1}
                  aria-label={pinName(p, i)}
                  data-item={p.item}
                >
                  <p className="lbl">
                    <span>{pinKicker(p, i)}</span>
                  </p>
                  <PinTitle pin={p} />
                  {own.length > 0 && (
                    <ul className="board-row-edges" aria-label={`Connections of pin ${i + 1}`}>
                      {own.map((e) => (
                        <li key={`${e.other}|${e.kind}`}>
                          <i className={`key key-${e.kind}`} aria-hidden="true" />
                          {e.label}: {e.n}. {pins[e.n - 1]?.snapshot.title}
                        </li>
                      ))}
                    </ul>
                  )}
                  <RemoveButton pin={p} i={i} onRemove={() => remove(i)} />
                </li>
              );
            })}
          </ol>
        )}
        {edgesFailed ? (
          <p className="insp-note" role="status">
            {UNAVAILABLE}
          </p>
        ) : (
          !coCoverageChecked &&
          pins.length > 1 && <p className="insp-note">Covered together: unavailable right now</p>
        )}
        {announcer}
      </section>
    );
  }

  return (
    <section
      className="glass board"
      role="dialog"
      aria-modal="false"
      aria-labelledby={titleId}
      data-testid="board"
      data-edges={laid.length}
      onKeyDown={onKeyDown}
    >
      <div className="ghead">
        <h2 id={titleId}>Investigation board</h2>
        <span className="sub">{count}</span>
        <div className="end">
          {actions}
          {close}
        </div>
      </div>
      {shareRow}
      {edgesFailed ? (
        <p className="board-legend" role="status">
          {UNAVAILABLE}
        </p>
      ) : (
        <ul className="board-legend" aria-label="Edge types">
          {EDGE_LEGEND.map(({ kind, label }) => (
            <li key={kind}>
              <i className={`key key-${kind}`} aria-hidden="true" />
              {kind === "co_covered" && !coCoverageChecked
                ? "Covered together: unavailable right now"
                : label}
            </li>
          ))}
        </ul>
      )}
      {/* The memo docks beside the canvas, never over it: no card can sit under it. */}
      <div className="board-body">
        <div className="field" ref={fieldRef} data-testid="board-field">
          <svg className="board-edges" aria-hidden="true">
            <defs>
              <linearGradient
                id={`${uid}-aurora`}
                gradientUnits="userSpaceOnUse"
                x1="0"
                y1="0"
                x2={Math.max(1, size.w)}
                y2="0"
              >
                <stop offset="0" stopColor="var(--aurora-start)" />
                <stop offset="1" stopColor="var(--aurora-end)" />
              </linearGradient>
            </defs>
            {laid.map((e) => (
              <path
                key={e.key}
                d={e.d}
                className={`edge edge-${e.kind}`}
                style={e.kind === "same_thread" ? { stroke: `url(#${uid}-aurora)` } : undefined}
              />
            ))}
          </svg>
          {/* A label no spot along its edge keeps clear of the cards goes under them. */}
          {laid.map((e) => (
            <span
              key={e.key}
              className={`elabel elabel-${e.kind}${e.under ? " under" : ""}`}
              style={{ left: e.x, top: e.y }}
              aria-hidden="true"
            >
              {e.label}
            </span>
          ))}
          <ol className="board-pins" aria-label="Pins">
            {pins.map((p, i) => {
              const at = placed(p);
              return (
                <PinCard
                  key={p.item}
                  pin={p}
                  index={i}
                  left={PAD + at.x * spanX}
                  top={PAD + at.y * spanY}
                  x={at.x}
                  y={at.y}
                  dragging={drag?.item === p.item}
                  hintId={`${uid}-hint`}
                  handlers={handlers}
                />
              );
            })}
          </ol>
          <p id={`${uid}-hint`} hidden>
            Arrow keys move it; with Shift, further.
          </p>
          {empty}
          <ul className="sr-only" aria-label="Connections">
            {edges.map((e) => (
              <li key={`${e.a}|${e.b}|${e.kind}`}>
                Pins {number.get(e.a)} and {number.get(e.b)}: {e.label}
              </li>
            ))}
          </ul>
        </div>
        {memoPanel}
      </div>
      {announcer}
    </section>
  );
}
