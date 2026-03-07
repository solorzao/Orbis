"use client";

import { useState, useEffect, useCallback } from "react";
import dynamic from "next/dynamic";
import { Topic, GlobePoint, NewsArticle, PanelEntry, PanelFilters } from "@/types/news";
import { apiPointsToGlobePoints } from "@/lib/clustering";
import { fetchGlobeNews, fetchClusterArticles, fetchClusterSummary, fetchDensity } from "@/lib/api";
import TimeSlider from "@/components/TimeSlider";
import PanelQueue from "@/components/PanelQueue";
import TopicFilter from "@/components/TopicFilter";
import ThemeToggle from "@/components/ThemeToggle";

// Globe requires `window` — load without SSR
const Globe = dynamic(() => import("@/components/Globe"), { ssr: false });

export default function Home() {
  const [activeTopic, setActiveTopic] = useState<Topic>("All");

  const [allPoints, setAllPoints] = useState<GlobePoint[]>([]);
  const [apiError, setApiError] = useState(false);
  const [loading, setLoading] = useState(true);

  const [timeRange, setTimeRange] = useState<{ startTime: string; endTime: string } | null>(null);
  const [density, setDensity] = useState<{ hour: number; count: number }[]>([]);

  const MAX_PANELS = 5;
  const [panelQueue, setPanelQueue] = useState<PanelEntry[]>([]);
  const [expandedPanelId, setExpandedPanelId] = useState<string | null>(null);

  // Fetch density on mount
  useEffect(() => {
    fetchDensity()
      .then(setDensity)
      .catch(() => {});
  }, []);

  // Fetch globe data on mount and when timeRange changes
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchGlobeNews("24h", 500, timeRange?.startTime, timeRange?.endTime)
      .then((apiPoints) => {
        if (cancelled) return;
        setAllPoints(apiPointsToGlobePoints(apiPoints));
      })
      .catch(() => {
        if (cancelled) return;
        setAllPoints([]);
        setApiError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [timeRange]);

  // Filter points client-side — instant, no API call
  const points =
    activeTopic === "All" ? allPoints : allPoints.filter((p) => p.topic === activeTopic);

  const updatePanel = useCallback((panelId: string, updates: Partial<PanelEntry>) => {
    setPanelQueue((prev) => prev.map((p) => (p.panelId === panelId ? { ...p, ...updates } : p)));
  }, []);

  const mapArticles = (apiArticles: Awaited<ReturnType<typeof fetchClusterArticles>>): NewsArticle[] =>
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
          timeRange?.startTime,
          timeRange?.endTime,
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
        );
        updatePanel(panelId, { clusterSummary: result.summary, summaryLoading: false });
      } catch {
        updatePanel(panelId, { summaryLoading: false });
      }
    },
    [activeTopic, timeRange, updatePanel],
  );

  const handleLoadMore = useCallback(
    async (panelId: string, filters?: PanelFilters) => {
      const panel = panelQueue.find((p) => p.panelId === panelId);
      if (!panel || panel.loadingMore) return;

      updatePanel(panelId, { loadingMore: true });

      const topicFilter = activeTopic !== "All" ? activeTopic : undefined;
      const isFiltered = filters && (filters.sentiment || filters.search || filters.topics.length > 0);
      // When filters are active, use single in-panel topic for backend filter
      const inPanelTopic = filters?.topics?.length === 1 ? filters.topics[0] : undefined;

      try {
        const apiArticles = await fetchClusterArticles(
          panel.point.lat,
          panel.point.lng,
          0.75,
          isFiltered ? (inPanelTopic || topicFilter) : topicFilter,
          panel.point.locationName,
          isFiltered ? 0 : panel.articles.length,
          isFiltered ? 50 : 20,
          timeRange?.startTime,
          timeRange?.endTime,
          isFiltered ? (filters.sentiment || undefined) : undefined,
          isFiltered ? (filters.search || undefined) : undefined,
        );
        let mapped = mapArticles(apiArticles);

        // Backend only supports single topic — apply multi-topic client-side
        if (isFiltered && filters.topics.length > 1) {
          mapped = mapped.filter((a) => a.topicTags.some((t) => filters.topics.includes(t)));
        }

        if (isFiltered) {
          // Merge server-filtered results with existing articles (deduplicate by id).
          // This preserves already-loaded articles so clearing filters still works.
          const existingIds = new Set(panel.articles.map((a) => a.id));
          const newArticles = mapped.filter((a) => !existingIds.has(a.id));
          const allArticles = [...panel.articles, ...newArticles];
          updatePanel(panelId, {
            articles: allArticles,
            point: { ...panel.point, articles: allArticles },
            loadingMore: false,
          });
        } else {
          // Unfiltered: append next batch
          const allArticles = [...panel.articles, ...mapped];
          updatePanel(panelId, {
            articles: allArticles,
            point: { ...panel.point, articles: allArticles },
            loadingMore: false,
          });
        }
      } catch {
        updatePanel(panelId, { loadingMore: false });
      }
    },
    [panelQueue, activeTopic, timeRange, updatePanel],
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

  return (
    <main className="relative h-screen w-screen overflow-hidden bg-[var(--bg-page)]">
      {/* Globe */}
      <Globe points={points} onPointClick={handlePointClick} onZoomChange={handleZoomChange} />

      {/* Branding */}
      <div className="fixed top-3 left-3 z-50 flex items-center gap-2 sm:top-5 sm:left-6 sm:gap-3">
        <img
          src="/Orbis_logo_50_resize.png"
          alt="Orbis"
          className="h-7 w-7 sm:h-10 sm:w-10"
          style={{ filter: "drop-shadow(0 0 12px rgba(59, 130, 246, 0.4))" }}
        />
        <div>
          <h1
            className="text-sm font-bold tracking-[0.2em] text-[var(--text-primary)] uppercase sm:text-lg"
            style={{
              textShadow: "0 0 30px rgba(59, 130, 246, 0.3)",
            }}
          >
            Orbis
          </h1>
          <p className="hidden text-[9px] font-medium tracking-[0.3em] text-[var(--text-muted)] uppercase sm:block">
            Global Intelligence
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
      />

      {/* Time Slider + Status */}
      <TimeSlider
        density={density}
        onChange={setTimeRange}
        totalStories={points.reduce((sum, p) => sum + p.count, 0)}
        totalLocations={points.length}
        isLive={!apiError && !loading}
        isLoading={loading}
        isOffline={apiError}
      />
    </main>
  );
}
