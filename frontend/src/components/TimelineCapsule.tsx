"use client";

import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent,
  type Ref,
} from "react";
import { fetchVolume, type ApiHourlyVolume } from "@/lib/api";
import { useMinuteNow } from "@/hooks/useMinuteNow";
import { useReplay } from "@/hooks/useReplay";
import {
  HOUR_MS,
  LIVE_PRESETS,
  utcLabel,
  utcWeekday,
  windowLabel,
  type TimeWindow,
} from "@/lib/timeWindow";
import {
  CHART_DAYS,
  areaPath,
  chartDomain,
  chartPoints,
  dayTicks,
  linePath,
  markerX,
  placeDayLabels,
  rangeForDrag,
  smooth,
  volumeSeries,
  xForTime,
} from "@/lib/volumeChart";

/** The ingestion cadence: new stories land every 15 minutes. */
export const VOLUME_REFRESH_MS = 15 * 60_000;
/** How long the replay shows each day: 8 days, 8 globe requests in under 13 s. */
export const REPLAY_STEP_MS = 1600;

const DAY_MS = 24 * HOUR_MS;

// Chart geometry (mockup #area): the area from y 4 to 44, day labels below.
const CHART_H = 62;
const TOP = 4;
const BASE = 44;
const LABEL_Y = 59;
/** Before the chart is measured (and in tests): a typical width. */
const DEFAULT_WIDTH = 400;
/** Hours either side averaged into each point, so the area reads as a smooth flow. */
const SMOOTH_HOURS = 3;

const iso = (ms: number) => new Date(ms).toISOString();
const plural = (n: number, one: string, many: string) =>
  `${n.toLocaleString("en-GB")} ${n === 1 ? one : many}`;

/** The window's bounds in epoch ms: a live window ends now. */
function windowSpan(w: TimeWindow, now: number): { from: number; to: number } {
  if (w.kind === "live") return { from: now - w.hours * HOUR_MS, to: now };
  return { from: Date.parse(w.startTime), to: Date.parse(w.endTime) };
}

interface TimelineCapsuleProps {
  timeWindow: TimeWindow;
  onChange: (timeWindow: TimeWindow) => void;
  /** A window the visitor chose (a preset, a drag or the range inputs), not a replay's day. */
  onChoose?: (timeWindow: TimeWindow) => void;
  /** True when a replay starts, false when it ends (for the status pill). */
  onReplayChange?: (playing: boolean) => void;
  /** Stories and places on the globe for the window. */
  stories: number;
  places: number;
  /** Reduced motion: the replay's days change without the playhead sweeping. */
  reduced?: boolean;
  /** The replay button, for focus that has nowhere else to go (the Links chip). */
  playRef?: Ref<HTMLButtonElement>;
  /** The previous visit (ms): a dashed lavender line marks it on the chart (mockup). */
  lastVisit?: number | null;
  /**
   * With a thread selected, the play button replays how it spread (its
   * places lit in order of first report) instead of the last 7 days.
   */
  spread?: { title: string; playing: boolean; onPlay: () => void; onStop: () => void } | null;
}

/**
 * The timeline capsule (mockup .timeline): replay, a 7-day story-volume chart
 * with the current window as a soft band, and the window's label, story
 * count and presets. Drag on the chart (or use the two hidden range inputs)
 * to pick a range; a preset goes back to live. Replay steps the window
 * through the chart's UTC days, then returns to the window it started from;
 * picking a window stops it. With a thread selected it replays how the thread
 * spread instead (a day replay already playing keeps the button until it ends).
 */
export default function TimelineCapsule({
  timeWindow,
  onChange,
  onChoose,
  onReplayChange,
  stories,
  places,
  reduced = false,
  playRef,
  lastVisit = null,
  spread = null,
}: TimelineCapsuleProps) {
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  // "Now" to the minute, so the chart moves on as time passes. The server
  // can't know the visitor's clock: the chart's contents wait for the client.
  const now = useMinuteNow();

  // Story volume: once on mount, then at the ingestion cadence.
  const [volume, setVolume] = useState<ApiHourlyVolume[]>([]);
  useEffect(() => {
    const controller = new AbortController();
    const load = () =>
      fetchVolume(CHART_DAYS, controller.signal)
        .then((hours) => {
          if (!controller.signal.aborted) setVolume(hours);
        })
        .catch(() => {}); // keep the last chart; the next refresh tries again
    load();
    const id = setInterval(load, VOLUME_REFRESH_MS);
    return () => {
      controller.abort();
      clearInterval(id);
    };
  }, []);

  // The SVG is drawn at its real width, so labels and strokes keep their size.
  const chartRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(DEFAULT_WIDTH);
  useEffect(() => {
    const el = chartRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      const w = Math.round(entry.contentRect.width);
      if (w > 0) setWidth(w); // hidden (narrow screens): keep the last width
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const domain = useMemo(() => (now === null ? null : chartDomain(now)), [now]);
  const series = useMemo(
    () => (domain ? volumeSeries(volume, domain.start, domain.end) : []),
    [volume, domain],
  );
  // Complete hours only: the current one is still filling (new stories land every
  // 15 minutes), so it would read as a false dip at Today. The x scale keeps it.
  const points = useMemo(
    () => chartPoints(smooth(series.slice(0, -1), SMOOTH_HOURS), width, BASE - TOP, series.length),
    [series, width],
  );
  const ticks = useMemo(() => (domain ? dayTicks(domain.start, domain.end) : []), [domain]);

  // Replay: the chart's UTC days in turn, oldest first, then back.
  const replaySteps = useMemo<TimeWindow[]>(
    () =>
      ticks.map((tick) => ({
        kind: "range",
        startTime: iso(tick.dayStart),
        endTime: iso(tick.dayStart + DAY_MS),
      })),
    [ticks],
  );
  const replay = useReplay(replaySteps, REPLAY_STEP_MS, onChange, onReplayChange);
  /** The visitor picked a window: it replaces the replay rather than waiting for it. */
  const choose = (next: TimeWindow) => {
    replay.stop(false);
    onChange(next);
    onChoose?.(next);
  };

  // A thread selected while the days replay: the replay stops, back on the
  // window from before it, and the button replays the thread instead.
  const threadSelected = spread !== null;
  const { playing: dayReplaying, stop: stopDays } = replay;
  useEffect(() => {
    if (threadSelected && dayReplaying) stopDays();
  }, [threadSelected, dayReplaying, stopDays]);
  const replayStart = replay.step?.kind === "range" ? Date.parse(replay.step.startTime) : null;
  const replayDay =
    replayStart === null
      ? null
      : now !== null && Math.floor(replayStart / DAY_MS) === Math.floor(now / DAY_MS)
        ? "today"
        : utcWeekday(replayStart);

  // Dragging on the chart: the preview band follows the pointer; the window
  // (and the globe's fetch) changes once, on release.
  const drag = useRef<{ pointerId: number; x0: number } | null>(null);
  const [preview, setPreview] = useState<{ startTime: string; endTime: string } | null>(null);
  const localX = (e: PointerEvent<HTMLElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    return { x: e.clientX - rect.left, w: rect.width || width };
  };
  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (!domain || e.button !== 0) return;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    const { x, w } = localX(e);
    drag.current = { pointerId: e.pointerId, x0: x };
    setPreview(rangeForDrag(x, x, domain.start, domain.end, w));
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (!domain || drag.current?.pointerId !== e.pointerId) return;
    const { x, w } = localX(e);
    setPreview(rangeForDrag(drag.current.x0, x, domain.start, domain.end, w));
  };
  const onPointerUp = (e: PointerEvent<HTMLDivElement>) => {
    if (!domain || drag.current?.pointerId !== e.pointerId) return;
    const { x, w } = localX(e);
    const range = rangeForDrag(drag.current.x0, x, domain.start, domain.end, w);
    drag.current = null;
    setPreview(null);
    choose({ kind: "range", ...range });
  };
  const onPointerCancel = () => {
    drag.current = null;
    setPreview(null);
  };

  const label = replayDay
    ? `Replay · ${replayDay[0].toUpperCase()}${replayDay.slice(1)}`
    : windowLabel(timeWindow);
  const shown = preview ? { kind: "range" as const, ...preview } : (replay.step ?? timeWindow);
  const span = now === null ? null : windowSpan(shown, now);
  // The playhead marks the window's end, never later than now.
  const playheadTo = span && now !== null ? Math.min(span.to, now) : 0;
  const sweep = replay.playing && !reduced && span !== null;
  const x = (t: number) =>
    domain ? Math.min(width, Math.max(0, xForTime(t, domain.start, domain.end, width))) : 0;
  const lastVisitX =
    domain && lastVisit !== null ? markerX(lastVisit, domain.start, domain.end, width) : null;

  // Keyboard: the window's start and end as hour indices into the chart.
  const slots = domain ? Math.round((domain.end - domain.start) / HOUR_MS) : 0;
  const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
  const startIdx =
    domain && span ? clamp(Math.round((span.from - domain.start) / HOUR_MS), 0, slots - 1) : 0;
  const endIdx =
    domain && span ? clamp(Math.round((span.to - domain.start) / HOUR_MS), startIdx + 1, slots) : 1;
  const setIndices = (from: number, to: number) => {
    if (!domain) return;
    choose({
      kind: "range",
      startTime: iso(domain.start + from * HOUR_MS),
      endTime: iso(domain.start + to * HOUR_MS),
    });
  };

  const total = series.reduce((a, b) => a + b, 0);
  const peak = series.indexOf(Math.max(...series));
  const summary =
    domain && total > 0
      ? `${plural(total, "story", "stories")}, busiest hour ${utcLabel(domain.start + peak * HOUR_MS)}`
      : "no stories counted yet";

  return (
    <section
      className="pillbar timeline"
      data-testid="timeline"
      aria-label="Time window and replay"
    >
      <button
        type="button"
        ref={playRef}
        className="aurora-btn play"
        aria-label={
          replay.playing || spread?.playing
            ? "Stop replay"
            : spread
              ? `Replay how ${spread.title} spread`
              : "Replay the last 7 days"
        }
        onClick={() => {
          if (replay.playing) replay.stop();
          else if (spread) {
            if (spread.playing) spread.onStop();
            else spread.onPlay();
          } else replay.start(timeWindow);
        }}
      >
        <svg width="16" height="16" viewBox="0 0 10 10" fill="currentColor" aria-hidden="true">
          {replay.playing || spread?.playing ? (
            <rect x="2.2" y="2.2" width="5.6" height="5.6" rx="1" />
          ) : (
            <path d="M2.5 1.2l6.3 3.8-6.3 3.8z" />
          )}
        </svg>
      </button>

      <div
        ref={chartRef}
        className="chart"
        data-testid="timeline-chart"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerCancel}
      >
        <svg
          role="img"
          aria-label={`Story volume over 7 days; ${summary}; highlighted: ${label}`}
          viewBox={`0 0 ${width} ${CHART_H}`}
          width="100%"
          height={CHART_H}
        >
          <defs>
            <linearGradient id={`${uid}-fill`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" style={{ stopColor: "var(--timeline-fill)", stopOpacity: 0.45 }} />
              <stop offset="1" style={{ stopColor: "var(--timeline-fill)", stopOpacity: 0 }} />
            </linearGradient>
            <linearGradient id={`${uid}-stroke`} x1="0" y1="0" x2="1" y2="0">
              <stop offset="0" style={{ stopColor: "var(--aurora-start)" }} />
              <stop offset="0.55" style={{ stopColor: "var(--aurora-mid)" }} />
              <stop offset="1" style={{ stopColor: "var(--aurora-end)" }} />
            </linearGradient>
          </defs>
          {span && (
            <rect
              className="band"
              x={x(span.from)}
              y={TOP - 2}
              width={Math.max(6, x(span.to) - x(span.from))}
              height={BASE - TOP + 4}
              rx={6}
            />
          )}
          <g transform={`translate(0 ${TOP})`}>
            <path d={areaPath(points, BASE - TOP)} fill={`url(#${uid}-fill)`} />
            <path
              d={linePath(points)}
              fill="none"
              stroke={`url(#${uid}-stroke)`}
              strokeWidth={1.6}
            />
          </g>
          {lastVisitX !== null && (
            <g className="last-visit" data-testid="last-visit-marker">
              <line
                x1={lastVisitX}
                x2={lastVisitX}
                y1={TOP}
                y2={BASE}
                stroke="var(--accent-lavender)"
                strokeDasharray="2 3"
              />
              <circle cx={lastVisitX} cy={TOP} r={2.5} fill="var(--accent-lavender)">
                <title>Your last visit</title>
              </circle>
            </g>
          )}
          {span && (
            <g
              // A new key per day restarts the sweep from that day's start.
              key={sweep ? `sweep-${replay.index}` : "playhead"}
              className={sweep ? "playhead sweep" : "playhead"}
              style={
                {
                  transform: `translateX(${x(playheadTo)}px)`,
                  "--from": `${x(span.from)}px`,
                  "--to": `${x(playheadTo)}px`,
                  "--step": `${REPLAY_STEP_MS}ms`,
                } as CSSProperties
              }
            >
              <line x1={0} x2={0} y1={TOP - 2} y2={BASE + 2} />
              <circle cx={0} cy={TOP - 2} r={3.5} />
            </g>
          )}
          {placeDayLabels(ticks, x, width).map(({ tick, x: labelX }) => (
            <text
              key={tick.dayStart}
              x={labelX}
              y={LABEL_Y}
              textAnchor="middle"
              className={tick.label === "Today" ? "day today" : "day"}
            >
              {tick.label}
            </text>
          ))}
        </svg>
        {domain && (
          <>
            <input
              type="range"
              className="sr-only"
              aria-label="Window start"
              min={0}
              max={slots - 1}
              step={1}
              value={startIdx}
              aria-valuetext={utcLabel(domain.start + startIdx * HOUR_MS)}
              onChange={(e) => setIndices(Math.min(Number(e.target.value), endIdx - 1), endIdx)}
            />
            <input
              type="range"
              className="sr-only"
              aria-label="Window end"
              min={1}
              max={slots}
              step={1}
              value={endIdx}
              aria-valuetext={utcLabel(domain.start + endIdx * HOUR_MS)}
              onChange={(e) => setIndices(startIdx, Math.max(Number(e.target.value), startIdx + 1))}
            />
          </>
        )}
      </div>

      <div className="meta">
        <span className="pos" data-testid="timeline-label">
          {label}
        </span>
        <span className="count">
          {plural(stories, "story", "stories")} · {plural(places, "place", "places")}
        </span>
        <div className="pr" role="group" aria-label="Time window presets">
          {LIVE_PRESETS.map((p) => (
            <button
              key={p.hours}
              type="button"
              aria-pressed={
                !replay.playing && timeWindow.kind === "live" && timeWindow.hours === p.hours
              }
              onClick={() => choose({ kind: "live", hours: p.hours })}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      <span role="status" className="sr-only">
        {replayDay ? `Showing ${replayDay}` : ""}
      </span>
    </section>
  );
}
