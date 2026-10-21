"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BOARD_KEY,
  EMPTY_BOARD,
  MAX_PINS,
  addPin,
  applyResolved,
  boardFromJson,
  mergePins,
  movePin,
  readBoard,
  removePin,
  writeBoard,
  type BoardState,
  type Pin,
  type PinSnapshot,
  type ResolvedItem,
} from "@/lib/board";

/** localStorage, or null where reading it throws (blocked): the board then lives in memory. */
function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export interface BoardControls {
  /** The stored board has been read (it can't be on the server, or before hydration). */
  ready: boolean;
  pins: Pin[];
  /** 20 pins: no more fit. */
  full: boolean;
  has: (item: string) => boolean;
  /** Pin it, or unpin it when it is in; "full" when there is no room. */
  toggle: (item: string, snapshot: PinSnapshot) => "pinned" | "unpinned" | "full";
  unpin: (item: string) => void;
  move: (item: string, x: number, y: number) => void;
  /** Fresh snapshots from /api/board/resolve (merged threads take their new id). */
  refresh: (results: readonly ResolvedItem[]) => void;
  /** Add shared pins the board lacks, as far as there is room. */
  merge: (entries: readonly { item: string; snapshot: PinSnapshot }[]) => {
    added: number;
    skipped: number;
  };
}

/**
 * The investigation board, kept in localStorage ("orbis-board-v1") and in
 * memory when storage is blocked or full. Read once mounted (the server has
 * no storage), written on every change, and followed when another tab
 * changes it.
 */
export function useBoard(): BoardControls {
  const [state, setState] = useState<{ ready: boolean; board: BoardState }>({
    ready: false,
    board: EMPTY_BOARD,
  });
  // The board as last set, so an action can answer at once (pinned or full).
  const boardRef = useRef(state.board);

  const set = useCallback((next: BoardState) => {
    if (next === boardRef.current) return;
    boardRef.current = next;
    setState({ ready: true, board: next });
  }, []);

  useEffect(() => {
    const board = readBoard(storage());
    boardRef.current = board;
    // Read after mount on purpose: the server rendered an empty board.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setState({ ready: true, board });
    const onStorage = (e: StorageEvent) => {
      if (e.key !== BOARD_KEY) return;
      const next = boardFromJson(e.newValue);
      boardRef.current = next;
      setState({ ready: true, board: next });
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  useEffect(() => {
    if (state.ready) writeBoard(state.board, storage());
  }, [state]);

  const toggle = useCallback(
    (item: string, snapshot: PinSnapshot) => {
      const board = boardRef.current;
      if (board.pins.some((p) => p.item === item)) {
        set(removePin(board, item));
        return "unpinned" as const;
      }
      if (board.pins.length >= MAX_PINS) return "full" as const;
      set(addPin(board, item, snapshot, Date.now()));
      return "pinned" as const;
    },
    [set],
  );
  const unpin = useCallback((item: string) => set(removePin(boardRef.current, item)), [set]);
  const move = useCallback(
    (item: string, x: number, y: number) => set(movePin(boardRef.current, item, x, y)),
    [set],
  );
  const refresh = useCallback(
    (results: readonly ResolvedItem[]) => set(applyResolved(boardRef.current, results)),
    [set],
  );
  const merge = useCallback(
    (entries: readonly { item: string; snapshot: PinSnapshot }[]) => {
      const { state: next, added, skipped } = mergePins(boardRef.current, entries, Date.now());
      set(next);
      return { added, skipped };
    },
    [set],
  );

  const { pins } = state.board;
  const items = useMemo(() => new Set(pins.map((p) => p.item)), [pins]);
  const has = useCallback((item: string) => items.has(item), [items]);

  return {
    ready: state.ready,
    pins,
    full: pins.length >= MAX_PINS,
    has,
    toggle,
    unpin,
    move,
    refresh,
    merge,
  };
}
