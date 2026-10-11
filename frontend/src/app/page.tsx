"use client";

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import dynamic from "next/dynamic";
import { AnimatePresence } from "framer-motion";
import { Topic, GlobePoint, NewsArticle, PanelEntry, PanelFilters } from "@/types/news";
import { apiPointsToGlobePoints, filterPointsByTopic } from "@/lib/clustering";
import { fetchGlobeNews, fetchClusterArticles, fetchClusterSummary, fetchDensity } from "@/lib/api";
import { useAgent } from "@/hooks/useAgent";
import type { Citation, GlobeAction } from "@/hooks/useAgent";
import TimeSlider from "@/components/TimeSlider";
import PanelQueue from "@/components/PanelQueue";
import TopicFilter from "@/components/TopicFilter";
import ThemeToggle from "@/components/ThemeToggle";
import AgentPanel from "@/components/AgentPanel";

// Globe requires `window` — load without SSR
const Globe = dynamic(() => import("@/components/Globe"), { ssr: false });

export default function Home() {
  const [activeTopic, setActiveTopic] = useState<Topic>("All");

  const [allPoints, setAllPoints] = useState<GlobePoint[]>([]);
  const [apiError, setApiError] = useState(false);
  const [loading, setLoading] = useState(true);

  const [timeRange, setTimeRange] = useState<{ startTime: string; endTime: string } | null>(null);
  const [density, setDensity] = useState<{ hour: number; count: number }[]>([]);
  const [dayOffset, setDayOffset] = useState(0);
  const [hasOlderData, setHasOlderData] = useState(true);

  const MAX_PANELS = 5;
  const [panelQueue, setPanelQueue] = useState<PanelEntry[]>([]);
  const [expandedPanelId, setExpandedPanelId] = useState<string | null>(null);

  // Snapshot of "now" captured at mount and when the user changes the day,
  // so derived date math stays pure during render.
  const [nowTs, setNowTs] = useState(() => Date.now());

  // Agent panel
  const [agentOpen, setAgentOpen] = useState(false);
  const globeControlsRef = useRef<{
    flyTo: (lat: number, lng: number, altitude: number) => void;
  } | null>(null);

  // Track time slider height so the chat icon can sit above it on mobile
  const [sliderHeight, setSliderHeight] = useState(0);
  const sliderRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = sliderRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      setSliderHeight(entry.contentRect.height);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const handleDayChange = useCallback((newOffset: number) => {
    const clamped = Math.max(0, Math.min(6, newOffset));
    setDayOffset(clamped);
    setTimeRange(null);
    setNowTs(Date.now());
    setLoading(true);
  }, []);

  const dayWindow = useMemo(
    () =>
      dayOffset === 0
        ? null
        : (() => {
            const windowEnd = new Date(nowTs - dayOffset * 86400000);
            const windowStart = new Date(windowEnd.getTime() - 86400000);
            return { startTime: windowStart.toISOString(), endTime: windowEnd.toISOString() };
          })(),
    [dayOffset, nowTs],
  );

  const handleGlobeAction = useCallback((action: GlobeAction) => {
    if (action.type === "flyTo" && globeControlsRef.current) {
      const altitude = action.zoom ? 300 / action.zoom : 2.0;
      globeControlsRef.current.flyTo(action.lat, action.lng, altitude);
    }
  }, []);

  const {
    messages: agentMessages,
    isLoading: agentLoading,
    isDisabled: agentDisabled,
    activeTools,
    ask: agentAsk,
    stop: agentStop,
    clear: agentClear,
  } = useAgent({ onGlobeAction: handleGlobeAction });

  const handleCitationClick = useCallback((citation: Citation) => {
    if (globeControlsRef.current && citation.lat && citation.lng) {
      globeControlsRef.current.flyTo(citation.lat, citation.lng, 1.5);
    }
    if (citation.url) {
      window.open(citation.url, "_blank", "noopener,noreferrer");
    }
  }, []);

  // Fetch density when dayOffset changes (with cancellation to prevent 429s)
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      fetchDensity(dayOffset)
        .then((d) => {
          if (cancelled) return;
          setDensity(d);
          if (dayOffset < 6) {
            fetchDensity(dayOffset + 1)
              .then((older) => {
                if (cancelled) return;
                setHasOlderData(older.some((h) => h.count > 0));
              })
              .catch(() => {
                if (!cancelled) setHasOlderData(false);
              });
          } else {
            setHasOlderData(false);
          }
        })
        .catch(() => {
          if (!cancelled) setDensity([]);
        });
    }, 150);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [dayOffset]);

  // Fetch globe data on mount and when timeRange or dayOffset changes
  useEffect(() => {
    let cancelled = false;
    const effectiveRange = timeRange ?? dayWindow;
    const timer = setTimeout(() => {
      fetchGlobeNews("24h", 500, effectiveRange?.startTime, effectiveRange?.endTime)
        .then((apiPoints) => {
          if (cancelled) return;
          setAllPoints(apiPointsToGlobePoints(apiPoints));
          setApiError(false);
        })
        .catch(() => {
          if (cancelled) return;
          setAllPoints([]);
          setApiError(true);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 150);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [timeRange, dayWindow]);

  // Filter points client-side — instant, no API call
  const points = filterPointsByTopic(allPoints, activeTopic);

  const updatePanel = useCallback((panelId: string, updates: Partial<PanelEntry>) => {
    setPanelQueue((prev) => prev.map((p) => (p.panelId === panelId ? { ...p, ...updates } : p)));
  }, []);

  const mapArticles = (
    apiArticles: Awaited<ReturnType<typeof fetchClusterArticles>>,
  ): NewsArticle[] =>
    apiArticles.map((a) => ({
      id: a.id,
      title: a.title,
      summary: a.summary ?? undefined,
      sourceUrl: a.source_url,
      sourceName: a.source_name,
      publishedAt: a.published_at,
      latitude: a.latitude,
      longitude: a.longitude,
      countryCode: a.country_code,
      topicTags: a.topic_tags,
      sentimentScore: a.sentiment_score,
    }));

  const fetchPanelData = useCallback(
    async (panelId: string, point: GlobePoint) => {
      const topicFilter = activeTopic !== "All" ? activeTopic : undefined;

      try {
        const apiArticles = await fetchClusterArticles(
          point.lat,
          point.lng,
          0.75,
          topicFilter,
          point.locationName,
          0,
          10,
          (timeRange ?? dayWindow)?.startTime,
          (timeRange ?? dayWindow)?.endTime,
        );
        const mapped = mapArticles(apiArticles);
        updatePanel(panelId, {
          articles: mapped,
          point: { ...point, articles: mapped },
          articlesLoading: false,
        });
      } catch {
        updatePanel(panelId, { articlesLoading: false });
      }

      try {
        const result = await fetchClusterSummary(
          point.lat,
          point.lng,
          0.75,
          point.locationName,
          topicFilter,
          (timeRange ?? dayWindow)?.startTime,
          (timeRange ?? dayWindow)?.endTime,
        );
        updatePanel(panelId, { clusterSummary: result.summary, summaryLoading: false });
      } catch {
        updatePanel(panelId, { summaryLoading: false });
      }
    },
    [activeTopic, timeRange, dayWindow, updatePanel],
  );

  const handleLoadMore = useCallback(
    async (panelId: string, filters?: PanelFilters) => {
      const panel = panelQueue.find((p) => p.panelId === panelId);
      if (!panel || panel.loadingMore) return;

      updatePanel(panelId, { loadingMore: true });

      const topicFilter = activeTopic !== "All" ? activeTopic : undefined;
      const isFiltered =
        filters && (filters.sentiment || filters.search || filters.topics.length > 0);

      try {
        // When filters are active, load ALL articles (unfiltered) so the
        // client-side filter has the full dataset. Button disappears because
        // count === articles.length. Clearing filters shows everything.
        const apiArticles = await fetchClusterArticles(
          panel.point.lat,
          panel.point.lng,
          0.75,
          topicFilter,
          panel.point.locationName,
          isFiltered ? 0 : panel.articles.length,
          isFiltered ? 50 : 20,
          (timeRange ?? dayWindow)?.startTime,
          (timeRange ?? dayWindow)?.endTime,
        );
        const mapped = mapArticles(apiArticles);
        const allArticles = isFiltered ? mapped : [...panel.articles, ...mapped];
        updatePanel(panelId, {
          articles: allArticles,
          point: { ...panel.point, articles: allArticles, count: allArticles.length },
          loadingMore: false,
        });
      } catch {
        updatePanel(panelId, { loadingMore: false });
      }
    },
    [panelQueue, activeTopic, timeRange, dayWindow, updatePanel],
  );

  const handlePointClick = useCallback(
    (point: GlobePoint) => {
      // Check if already in queue
      const existing = panelQueue.find((p) => p.point.id === point.id);
      if (existing) {
        setExpandedPanelId(existing.panelId);
        return;
      }

      const panelId = `${point.id}-${Date.now()}`;
      const newEntry: PanelEntry = {
        panelId,
        point,
        articles: [],
        clusterSummary: null,
        articlesLoading: true,
        summaryLoading: true,
        createdAt: Date.now(),
      };

      setPanelQueue((prev) => {
        let next = [...prev, newEntry];
        if (next.length > MAX_PANELS) {
          const oldest = next
            .filter((p) => p.panelId !== panelId)
            .sort((a, b) => a.createdAt - b.createdAt)[0];
          if (oldest) next = next.filter((p) => p.panelId !== oldest.panelId);
        }
        return next;
      });

      setExpandedPanelId(panelId);
      fetchPanelData(panelId, point);
    },
    [panelQueue, fetchPanelData],
  );

  const handleZoomChange = useCallback(() => {}, []);

  const handleClosePanel = useCallback((panelId: string) => {
    setPanelQueue((prev) => prev.filter((p) => p.panelId !== panelId));
    setExpandedPanelId((prev) => (prev === panelId ? null : prev));
  }, []);

  const handleMinimizePanel = useCallback(() => {
    setExpandedPanelId(null);
  }, []);

  const handleExpandPanel = useCallback((panelId: string) => {
    setExpandedPanelId(panelId);
  }, []);

  const handleFiltersChange = useCallback(
    (panelId: string, filters: PanelFilters, filterSummary: string | null) => {
      updatePanel(panelId, { filters, filterSummary });
    },
    [updatePanel],
  );

  return (
    <main className="relative h-screen w-screen overflow-hidden bg-[var(--bg-page)]">
      {/* Globe */}
      <Globe
        points={points}
        onPointClick={handlePointClick}
        onZoomChange={handleZoomChange}
        onReady={(controls) => {
          globeControlsRef.current = controls;
        }}
      />

      {/* Branding */}
      <div className="fixed top-3 left-3 z-50 flex items-center gap-2 sm:top-5 sm:left-6 sm:gap-3">
        <img
          src="/Orbis_logo_50_resize.png"
          alt="Orbis"
          className="h-7 w-7 sm:h-10 sm:w-10"
          style={{ filter: "drop-shadow(0 0 12px rgba(0, 212, 255, 0.5))" }}
        />
        <div>
          <h1
            className="text-sm font-bold tracking-[0.2em] text-[var(--text-primary)] uppercase sm:text-lg"
            style={{
              fontFamily: "var(--font-brand), sans-serif",
              textShadow: "0 0 30px rgba(0, 212, 255, 0.4)",
            }}
          >
            Orbis
          </h1>
          <p className="hidden text-[9px] font-medium tracking-[0.3em] text-[var(--text-motto)] uppercase sm:block">
            Every Story, Everywhere
          </p>
        </div>
      </div>

      {/* Topic Filters */}
      <TopicFilter activeTopic={activeTopic} onTopicChange={setActiveTopic} />

      {/* Theme Toggle */}
      <ThemeToggle />

      {/* Panel Queue */}
      <PanelQueue
        panelQueue={panelQueue}
        expandedPanelId={expandedPanelId}
        onExpandPanel={handleExpandPanel}
        onClosePanel={handleClosePanel}
        onMinimizePanel={handleMinimizePanel}
        onLoadMore={handleLoadMore}
        onFiltersChange={handleFiltersChange}
      />

      {/* Agent Toggle */}
      {!agentOpen && (
        <button
          onClick={() => setAgentOpen(true)}
          className="fixed left-3 z-40 flex h-11 w-11 items-center justify-center rounded-full border border-[var(--border-subtle)] text-blue-400 transition-all hover:border-blue-500/30 hover:bg-blue-500/10 sm:!bottom-8 sm:left-6 sm:h-12 sm:w-12"
          style={{
            background: "var(--surface-overlay)",
            backdropFilter: "blur(12px)",
            bottom: `${sliderHeight + 24}px`,
          }}
          aria-label="Toggle agent panel"
          data-testid="agent-toggle"
        >
          <svg
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M3 15a2 2 0 0 0 2 2h12l4 4V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2z" />
          </svg>
          {agentMessages.length > 0 && (
            <span className="absolute -top-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full bg-blue-500 text-[9px] font-bold text-white">
              {agentMessages.length}
            </span>
          )}
        </button>
      )}

      {/* Agent Panel */}
      <AnimatePresence>
        {agentOpen && (
          <AgentPanel
            messages={agentMessages}
            isLoading={agentLoading}
            isDisabled={agentDisabled}
            activeTools={activeTools}
            onAsk={agentAsk}
            onStop={agentStop}
            onClear={agentClear}
            onCitationClick={handleCitationClick}
            onClose={() => setAgentOpen(false)}
          />
        )}
      </AnimatePresence>

      {/* Time Slider + Status */}
      <TimeSlider
        density={density}
        onChange={(range) => {
          setTimeRange(range);
          setLoading(true);
        }}
        onDayChange={handleDayChange}
        dayOffset={dayOffset}
        hasOlderData={hasOlderData}
        totalStories={points.reduce((sum, p) => sum + p.count, 0)}
        totalLocations={points.length}
        isLive={!apiError && !loading && dayOffset === 0}
        isLoading={loading}
        isOffline={apiError}
        sliderRef={sliderRef}
      />
    </main>
  );
}
