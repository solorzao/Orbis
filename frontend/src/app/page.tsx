"use client";

import { useState, useEffect, useCallback } from "react";
import dynamic from "next/dynamic";
import { Topic, GlobePoint, NewsArticle } from "@/types/news";
import { apiPointsToGlobePoints } from "@/lib/clustering";
import { fetchGlobeNews, fetchClusterArticles, fetchClusterSummary } from "@/lib/api";
import NewsPanel from "@/components/NewsPanel";
import TopicFilter from "@/components/TopicFilter";
import ThemeToggle from "@/components/ThemeToggle";

// Globe requires `window` — load without SSR
const Globe = dynamic(() => import("@/components/Globe"), { ssr: false });

export default function Home() {
  const [activeTopic, setActiveTopic] = useState<Topic>("All");
  const [selectedPoint, setSelectedPoint] = useState<GlobePoint | null>(null);

  const [allPoints, setAllPoints] = useState<GlobePoint[]>([]);
  const [apiError, setApiError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [clusterSummary, setClusterSummary] = useState<string | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [articlesLoading, setArticlesLoading] = useState(false);

  // Fetch all points once on mount
  useEffect(() => {
    let cancelled = false;
    setApiError(false);
    setLoading(true);
    fetchGlobeNews()
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
    return () => { cancelled = true; };
  }, []);

  // Filter points client-side — instant, no API call
  const points = activeTopic === "All"
    ? allPoints
    : allPoints.filter((p) => p.topic === activeTopic);

  const handlePointClick = useCallback(async (point: GlobePoint) => {
    setSelectedPoint(point);
    setClusterSummary(null);
    setArticlesLoading(true);
    setSummaryLoading(true);

    // Sequential: fetch articles first, then summary.
    // This way the summary endpoint hits the Redis cache populated by
    // the articles call instead of making a duplicate GDELT request.
    const topicFilter = activeTopic !== "All" ? activeTopic : undefined;
    try {
      const articles = await fetchClusterArticles(
        point.lat,
        point.lng,
        5.0,
        topicFilter,
        point.locationName,
      );
      const mapped: NewsArticle[] = articles.map((a) => ({
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
      setSelectedPoint((prev) =>
        prev ? { ...prev, articles: mapped, count: mapped.length } : null,
      );
    } catch {
      // Keep the panel open with whatever we have
    } finally {
      setArticlesLoading(false);
    }

    // Now fetch summary — GDELT results are cached from the call above.
    // Skip if no articles matched the topic filter.
    try {
      const result = await fetchClusterSummary(
        point.lat,
        point.lng,
        5.0,
        point.locationName,
        topicFilter,
      );
      setClusterSummary(result.summary);
    } catch {
      // Summary unavailable — not critical
    } finally {
      setSummaryLoading(false);
    }
  }, [activeTopic]);

  const handleZoomChange = useCallback(() => {}, []);

  const handleClosePanel = useCallback(() => {
    setSelectedPoint(null);
    setClusterSummary(null);
    setSummaryLoading(false);
    setArticlesLoading(false);
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
            className="text-sm font-bold tracking-[0.2em] text-white uppercase sm:text-lg"
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

      {/* News Panel */}
      <NewsPanel
        point={selectedPoint}
        onClose={handleClosePanel}
        clusterSummary={clusterSummary}
        summaryLoading={summaryLoading}
        articlesLoading={articlesLoading}
      />

      {/* Bottom status bar */}
      <div className="fixed bottom-3 left-1/2 z-30 -translate-x-1/2 sm:bottom-4">
        <div
          className="flex items-center gap-2 rounded-full border border-[var(--border-subtle)] px-3 py-1.5 text-[9px] tracking-wider text-[var(--text-secondary)] sm:gap-3 sm:px-4 sm:py-2 sm:text-[10px]"
          style={{
            background: "var(--surface-overlay)",
            backdropFilter: "blur(12px)",
          }}
        >
          <span className="flex items-center gap-1.5">
            {apiError ? (
              <span className="text-red-400 text-xs font-semibold tracking-wider">OFFLINE</span>
            ) : loading ? (
              <>
                <span className="h-2 w-2 animate-spin rounded-full border border-blue-400/30 border-t-blue-400" />
                <span className="text-blue-400 text-xs font-semibold tracking-wider">LOADING</span>
              </>
            ) : (
              <>
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
                </span>
                <span className="text-emerald-400 text-xs font-semibold tracking-wider">LIVE</span>
              </>
            )}
          </span>
          <span className="text-[var(--text-muted)]">|</span>
          <span>{points.reduce((sum, p) => sum + p.count, 0)} stories tracked</span>
          <span className="text-[var(--text-muted)]">|</span>
          <span>{points.length} locations</span>
        </div>
      </div>
    </main>
  );
}
