"use client";

import { useEffect, useRef, useState } from "react";
import type { Topic } from "@/types/news";
import {
  fetchThread,
  fetchThreads,
  toThread,
  toThreadDetail,
  type Thread,
  type ThreadDetail,
} from "@/lib/threads";
import type { LiveHours, TimeWindow } from "@/lib/timeWindow";
import { FETCH_DEBOUNCE_MS } from "@/hooks/useGlobePoints";

const NO_THREADS: Thread[] = [];

interface Result {
  hours: LiveHours;
  topic: Topic;
  threads: Thread[];
  error: boolean;
}

/**
 * The developing stories for a live window and topic, fetched only while the
 * Threads layer is on (`enabled`); a range or a replay has none (the API
 * serves live windows). As useLinks: a new window or topic cancels the last
 * request and ignores its answer if it comes anyway, the last threads stay
 * while the next load, and off forgets them.
 */
export function useThreads(
  timeWindow: TimeWindow,
  topic: Topic,
  enabled: boolean,
): { threads: Thread[]; loading: boolean; error: boolean } {
  const [result, setResult] = useState<Result | null>(null);
  const hours = timeWindow.kind === "live" ? timeWindow.hours : null;
  const on = enabled && hours !== null;

  useEffect(() => {
    if (!on || hours === null) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      fetchThreads({ hours, topic, signal: controller.signal })
        .then((api) => {
          if (controller.signal.aborted) return;
          setResult({ hours, topic, threads: api.map(toThread), error: false });
        })
        .catch(() => {
          if (controller.signal.aborted) return;
          setResult({ hours, topic, threads: NO_THREADS, error: true });
        });
    }, FETCH_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [on, hours, topic]);

  // Off forgets the last answer: turned on again, an old error must not show
  // before the new request answers.
  if (!enabled && result !== null) setResult(null);
  if (!on) return { threads: NO_THREADS, loading: false, error: false };
  const current = result !== null && result.hours === hours && result.topic === topic;
  return {
    threads: result?.threads ?? NO_THREADS,
    error: result?.error ?? false,
    loading: !current,
  };
}

/**
 * The selected thread's detail (its spread, key entities and first stories),
 * or none. A new thread aborts the last request; only the thread asked for
 * is ever returned. A thread merged into another answers as that thread:
 * `onMerged` gets its id, so the caller selects it (and shares it) instead.
 */
export function useThread(
  id: number | null,
  onMerged?: (id: number) => void,
): {
  detail: ThreadDetail | null;
  loading: boolean;
  error: boolean;
} {
  const [result, setResult] = useState<{
    id: number;
    detail: ThreadDetail | null;
    error: boolean;
  } | null>(null);
  // The latest callback, without refetching when its identity changes.
  const onMergedRef = useRef(onMerged);
  useEffect(() => {
    onMergedRef.current = onMerged;
  });

  useEffect(() => {
    if (id === null) return;
    const controller = new AbortController();
    fetchThread({ id, signal: controller.signal })
      .then((api) => {
        if (!controller.signal.aborted) {
          setResult({ id, detail: toThreadDetail(api), error: false });
          if (api.id !== id) onMergedRef.current?.(api.id);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setResult({ id, detail: null, error: true });
      });
    return () => controller.abort();
  }, [id]);

  if (id === null) return { detail: null, loading: false, error: false };
  if (result?.id !== id) return { detail: null, loading: true, error: false };
  return { detail: result.detail, loading: false, error: result.error };
}
