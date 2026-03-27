"use client";

import { useState, useCallback, useRef, useMemo } from "react";

interface TimeSliderProps {
  density: { hour: number; count: number }[];
  onChange: (range: { startTime: string; endTime: string } | null) => void;
  onDayChange: (offsetDays: number) => void;
  dayOffset: number;
  hasOlderData: boolean;
  totalStories: number;
  totalLocations: number;
  isLive: boolean;
  isLoading: boolean;
  isOffline: boolean;
}

export default function TimeSlider({
  density,
  onChange,
  onDayChange,
  dayOffset,
  hasOlderData,
  totalStories,
  totalLocations,
  isLoading,
  isOffline,
}: TimeSliderProps) {
  // Range values: 0 = now, 24 = 24h ago
  // We invert for display: left = oldest (24), right = newest (0)
  // So rangeStart = hours ago for the START of window (larger number = further back)
  // rangeEnd = hours ago for the END of window (smaller number = more recent)
  const [rangeStart, setRangeStart] = useState(24); // 24h ago
  const [rangeEnd, setRangeEnd] = useState(0); // now
  // Reset range when dayOffset prop changes (React-recommended pattern)
  const [prevDay, setPrevDay] = useState(dayOffset);
  if (prevDay !== dayOffset) {
    setPrevDay(dayOffset);
    setRangeStart(24);
    setRangeEnd(0);
  }
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isFullRange = rangeStart === 24 && rangeEnd === 0;

  const presets = [
    { label: "1h", hours: 1 },
    { label: "6h", hours: 6 },
    { label: "12h", hours: 12 },
  ] as const;

  // Convert hours-ago to ISO string
  const hoursAgoToISO = useCallback(
    (hoursAgo: number): string => {
      const windowEnd = new Date(Date.now() - dayOffset * 86400000);
      const d = new Date(windowEnd.getTime() - hoursAgo * 3600000);
      return d.toISOString();
    },
    [dayOffset],
  );

  // Format hours-ago to display time
  const formatTime = useCallback((hoursAgo: number): string => {
    const d = new Date(Date.now() - hoursAgo * 3600000);
    return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }, []);

  // Debounced callback
  const emitChange = useCallback(
    (start: number, end: number) => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        if (start === 24 && end === 0 && dayOffset === 0) {
          onChange(null); // full range = no filter
        } else {
          onChange({
            startTime: hoursAgoToISO(start),
            endTime: hoursAgoToISO(end),
          });
        }
      }, 300);
    },
    [onChange, hoursAgoToISO, dayOffset],
  );

  const handleStartChange = useCallback(
    (value: number) => {
      const clamped = Math.max(value, rangeEnd + 1);
      setRangeStart(clamped);
      emitChange(clamped, rangeEnd);
    },
    [rangeEnd, emitChange],
  );

  const handleEndChange = useCallback(
    (value: number) => {
      const clamped = Math.min(value, rangeStart - 1);
      setRangeEnd(clamped);
      emitChange(rangeStart, clamped);
    },
    [rangeStart, emitChange],
  );

  const handleReset = useCallback(() => {
    setRangeStart(24);
    setRangeEnd(0);
    onChange(null);
  }, [onChange]);

  const handlePreset = useCallback(
    (hours: number) => {
      setRangeStart(hours);
      setRangeEnd(0);
      emitChange(hours, 0);
    },
    [emitChange],
  );

  // Capture "now" in state initializer (allowed to be impure) to keep memo pure.
  const [mountTs] = useState(() => Date.now());

  const dayLabel = useCallback(
    (offset: number): string => {
      if (offset === 0) return "Today";
      if (offset === 1) return "Yesterday";
      const d = new Date(mountTs - offset * 86400000);
      return d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
    },
    [mountTs],
  );

  const windowLabel = useMemo(() => dayLabel(dayOffset), [dayLabel, dayOffset]);

  // Day chips for direct day selection (today + 6 days back)
  const dayChips = useMemo(
    () =>
      Array.from({ length: 7 }, (_, i) => ({
        offset: i,
        label:
          i === 0
            ? "Today"
            : i === 1
              ? "Yday"
              : new Date(mountTs - i * 86400000).toLocaleDateString([], { weekday: "short" }),
      })),
    [mountTs],
  );

  // Sparkline max for scaling
  const maxCount = useMemo(() => Math.max(1, ...density.map((d) => d.count)), [density]);

  // Map density to 24 ordered bars (index 0 = 24h ago, index 23 = current hour)
  const bars = useMemo(() => {
    const now = new Date();
    const currentHour = now.getHours();
    return Array.from({ length: 24 }, (_, i) => {
      const hour = (currentHour - 23 + i + 24) % 24;
      const entry = density.find((d) => d.hour === hour);
      return entry?.count ?? 0;
    });
  }, [density]);

  // Tick labels at positions 0, 6, 12, 18, 24
  const ticks = useMemo(() => {
    return [24, 18, 12, 6, 0].map((hoursAgo) => ({
      hoursAgo,
      label: hoursAgo === 0 ? "Now" : formatTime(hoursAgo),
      pct: ((24 - hoursAgo) / 24) * 100,
    }));
  }, [formatTime]);

  return (
    <div
      data-testid="time-slider"
      className="fixed bottom-3 left-1/2 z-30 -translate-x-1/2 sm:bottom-6 flex flex-col items-center gap-1.5"
    >
      {/* Day selector chips */}
      <div
        className="flex items-center gap-1 rounded-full border border-[var(--border-subtle)] px-1.5 py-1"
        style={{ background: "var(--surface-overlay)", backdropFilter: "blur(12px)" }}
      >
        {dayChips.map(({ offset, label }) => {
          const isActive = dayOffset === offset;
          const isDisabled =
            offset > 0 && offset > dayOffset && !hasOlderData && offset > dayOffset;
          return (
            <button
              key={offset}
              onClick={() => onDayChange(offset)}
              disabled={isDisabled}
              className={`rounded-full px-2.5 py-1 text-[10px] font-semibold tracking-wide transition-all ${
                isActive
                  ? "bg-blue-500/20 text-blue-400 shadow-[0_0_8px_rgba(59,130,246,0.2)]"
                  : "text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-[var(--surface-hover)]"
              } disabled:opacity-20 disabled:pointer-events-none`}
              aria-label={dayLabel(offset)}
            >
              {label}
            </button>
          );
        })}
      </div>

      {/* Slider panel */}
      <div className="w-[80vw] max-w-2xl">
        <div
          className="rounded-2xl border border-[var(--border-subtle)] px-4 py-3 sm:px-5 sm:py-3.5"
          style={{
            background: "var(--surface-overlay)",
            backdropFilter: "blur(16px) saturate(1.4)",
          }}
        >
          {/* Time label + status */}
          <div className="mb-2 text-[10px] tracking-wider">
            {/* Row 1: status + date/time (always visible) */}
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 shrink-0">
                {/* Status indicator */}
                <span className="flex items-center gap-1.5">
                  {isOffline ? (
                    <span className="text-red-400 font-semibold">OFFLINE</span>
                  ) : isLoading ? (
                    <>
                      <span className="h-2 w-2 animate-spin rounded-full border border-blue-400/30 border-t-blue-400" />
                      <span className="text-blue-400 font-semibold">LOADING</span>
                    </>
                  ) : (
                    <>
                      <span className="relative flex h-2 w-2">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                        <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
                      </span>
                      <span className="text-emerald-400 font-semibold">LIVE</span>
                    </>
                  )}
                </span>
                <span className="text-[var(--text-muted)]">|</span>
                <span className="text-[var(--text-secondary)]">{totalStories} stories</span>
                <span className="text-[var(--text-muted)]">|</span>
                <span className="text-[var(--text-secondary)]">{totalLocations} locations</span>
                {/* Presets inline on desktop */}
                <span className="hidden sm:inline-flex items-center gap-1">
                  <span className="text-[var(--text-muted)]">|</span>
                  {presets.map(({ label, hours }) => {
                    const isActive = rangeStart === hours && rangeEnd === 0;
                    return (
                      <button
                        key={label}
                        onClick={() => handlePreset(hours)}
                        className={`rounded-full px-2 py-0.5 text-[9px] font-semibold tracking-wide transition-colors ${
                          isActive
                            ? "bg-blue-500/20 text-blue-400"
                            : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
                        }`}
                      >
                        {label}
                      </button>
                    );
                  })}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-[var(--text-secondary)] font-medium" suppressHydrationWarning>
                  {isFullRange
                    ? windowLabel
                    : `${windowLabel} · ${formatTime(rangeStart)} — ${formatTime(rangeEnd)}`}
                </span>
                {!isFullRange && (
                  <button
                    onClick={handleReset}
                    className="text-blue-400 hover:text-blue-300 font-medium"
                  >
                    Reset
                  </button>
                )}
              </div>
            </div>
            {/* Row 2: presets on mobile only */}
            <div className="flex items-center gap-1 mt-1.5 sm:hidden">
              {presets.map(({ label, hours }) => {
                const isActive = rangeStart === hours && rangeEnd === 0;
                return (
                  <button
                    key={label}
                    onClick={() => handlePreset(hours)}
                    className={`rounded-full px-2.5 py-0.5 text-[9px] font-semibold tracking-wide transition-colors ${
                      isActive
                        ? "bg-blue-500/20 text-blue-400"
                        : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
                    }`}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Sparkline + slider area */}
          <div className="relative h-10">
            {/* Sparkline bars */}
            <div className="absolute inset-x-0 bottom-0 flex h-8 items-end gap-px">
              {bars.map((count, i) => {
                const hoursAgo = 24 - i; // bar 0 = 24h ago, bar 23 = now
                const inRange = hoursAgo <= rangeStart && hoursAgo >= rangeEnd;
                const height = Math.max(2, (count / maxCount) * 100);
                return (
                  <div
                    key={i}
                    className="flex-1 rounded-t-sm transition-colors duration-150"
                    style={{
                      height: `${height}%`,
                      backgroundColor: inRange
                        ? "rgba(59, 130, 246, 0.3)"
                        : "rgba(59, 130, 246, 0.08)",
                    }}
                  />
                );
              })}
            </div>

            {/* Range highlight */}
            <div
              className="absolute bottom-0 h-8 rounded-sm pointer-events-none"
              style={{
                left: `${((24 - rangeStart) / 24) * 100}%`,
                right: `${(rangeEnd / 24) * 100}%`,
                backgroundColor: "rgba(59, 130, 246, 0.06)",
                borderLeft: "1px solid rgba(59, 130, 246, 0.4)",
                borderRight: "1px solid rgba(59, 130, 246, 0.4)",
              }}
            />

            {/* Start handle (left -- further back in time) */}
            <input
              type="range"
              min={0}
              max={24}
              step={1}
              value={24 - rangeStart}
              onChange={(e) => handleStartChange(24 - Number(e.target.value))}
              className="absolute bottom-0 left-0 w-full h-8 appearance-none bg-transparent pointer-events-none [&::-webkit-slider-thumb]:pointer-events-auto [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-1.5 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-blue-400 [&::-webkit-slider-thumb]:cursor-grab [&::-webkit-slider-thumb]:active:cursor-grabbing [&::-webkit-slider-thumb]:shadow-[0_0_6px_rgba(59,130,246,0.5)] [&::-moz-range-thumb]:pointer-events-auto [&::-moz-range-thumb]:appearance-none [&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:w-1.5 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:bg-blue-400 [&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:cursor-grab"
              style={{ zIndex: 2 }}
            />

            {/* End handle (right -- more recent) */}
            <input
              type="range"
              min={0}
              max={24}
              step={1}
              value={24 - rangeEnd}
              onChange={(e) => handleEndChange(24 - Number(e.target.value))}
              className="absolute bottom-0 left-0 w-full h-8 appearance-none bg-transparent pointer-events-none [&::-webkit-slider-thumb]:pointer-events-auto [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-1.5 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-blue-400 [&::-webkit-slider-thumb]:cursor-grab [&::-webkit-slider-thumb]:active:cursor-grabbing [&::-webkit-slider-thumb]:shadow-[0_0_6px_rgba(59,130,246,0.5)] [&::-moz-range-thumb]:pointer-events-auto [&::-moz-range-thumb]:appearance-none [&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:w-1.5 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:bg-blue-400 [&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:cursor-grab"
              style={{ zIndex: 2 }}
            />
          </div>

          {/* Tick labels */}
          <div className="relative mt-1 h-3">
            {ticks.map((tick) => (
              <span
                key={tick.hoursAgo}
                className="absolute text-[8px] text-[var(--text-muted)] -translate-x-1/2"
                style={{ left: `${tick.pct}%` }}
                suppressHydrationWarning
              >
                {tick.label}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
