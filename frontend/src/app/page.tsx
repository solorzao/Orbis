"use client";

import { useState, useEffect, useCallback } from "react";
import dynamic from "next/dynamic";
import { Topic, GlobePoint, NewsArticle } from "@/types/news";
import { mockArticles } from "@/lib/mockData";
import { clusterArticles, apiPointsToGlobePoints } from "@/lib/clustering";
import { fetchGlobeNews, fetchClusterArticles, fetchClusterSummary } from "@/lib/api";
import NewsPanel from "@/components/NewsPanel";
import TopicFilter from "@/components/TopicFilter";

// Globe requires `window` — load without SSR
const Globe = dynamic(() => import("@/components/Globe"), { ssr: false });

export default function Home() {
  const [activeTopic, setActiveTopic] = useState<Topic>("All");
  const [selectedPoint, setSelectedPoint] = useState<GlobePoint | null>(null);
  const [altitude, setAltitude] = useState(2.5);

  const [points, setPoints] = useState<GlobePoint[]>([]);
  const [usingMockData, setUsingMockData] = useState(false);
  const [clusterSummary, setClusterSummary] = useState<string | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;

    fetchGlobeNews(activeTopic)
      .then((apiPoints) => {
        if (cancelled) return;
        setPoints(apiPointsToGlobePoints(apiPoints));
        setUsingMockData(false);
      })
      .catch(() => {
        if (cancelled) return;
        // Fallback to mock data
        const filtered =
          activeTopic === "All"
            ? mockArticles
            : mockArticles.filter((a) => a.topicTags.includes(activeTopic));
        setPoints(clusterArticles(filtered, altitude));
        setUsingMockData(true);
      });

    return () => {
      cancelled = true;
    };
  }, [activeTopic, altitude]);

  const handlePointClick = useCallback(
    async (point: GlobePoint) => {
      setSelectedPoint(point);
      setClusterSummary(null);
      setSummaryLoading(false);

      if (usingMockData) return;

      setSummaryLoading(true);
      const articlesPromise = fetchClusterArticles(point.lat, point.lng);
      const summaryPromise = fetchClusterSummary(point.lat, point.lng);

      try {
        const articles = await articlesPromise;
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
      }

      try {
        const result = await summaryPromise;
        setClusterSummary(result.summary);
      } catch {
        // Summary unavailable — not critical
      } finally {
        setSummaryLoading(false);
      }
    },
    [usingMockData],
  );

  const handleZoomChange = useCallback((alt: number) => {
    setAltitude(alt);
  }, []);

  const handleClosePanel = useCallback(() => {
    setSelectedPoint(null);
    setClusterSummary(null);
    setSummaryLoading(false);
  }, []);

  return (
    <main className="relative h-screen w-screen overflow-hidden bg-[#030712]">
      {/* Globe */}
      <Globe points={points} onPointClick={handlePointClick} onZoomChange={handleZoomChange} />

      {/* Branding */}
      <div className="fixed top-5 left-6 z-40 flex items-center gap-3">
        <div className="relative">
          <div
            className="h-8 w-8 rounded-full"
            style={{
              background: "linear-gradient(135deg, #3B82F6 0%, #06B6D4 100%)",
              boxShadow: "0 0 20px rgba(59, 130, 246, 0.3)",
            }}
          />
          <div
            className="absolute inset-0 h-8 w-8 rounded-full"
            style={{
              background:
                "radial-gradient(circle at 30% 30%, rgba(255,255,255,0.2), transparent 60%)",
            }}
          />
        </div>
        <div>
          <h1
            className="text-lg font-bold tracking-[0.2em] text-white uppercase"
            style={{
              textShadow: "0 0 30px rgba(59, 130, 246, 0.3)",
            }}
          >
            Orbis
          </h1>
          <p className="text-[9px] font-medium tracking-[0.3em] text-slate-500 uppercase">
            Global Intelligence
          </p>
        </div>
      </div>

      {/* Topic Filters */}
      <TopicFilter activeTopic={activeTopic} onTopicChange={setActiveTopic} />

      {/* News Panel */}
      <NewsPanel
        point={selectedPoint}
        onClose={handleClosePanel}
        clusterSummary={clusterSummary}
        summaryLoading={summaryLoading}
      />

      {/* Bottom status bar */}
      <div className="fixed bottom-4 left-1/2 z-30 -translate-x-1/2">
        <div
          className="flex items-center gap-3 rounded-full border border-white/[0.05] px-4 py-2 text-[10px] tracking-wider text-slate-600"
          style={{
            background: "rgba(8, 12, 24, 0.5)",
            backdropFilter: "blur(12px)",
          }}
        >
          <span className="flex items-center gap-1.5">
            {usingMockData ? (
              <span className="text-amber-400 text-xs font-semibold tracking-wider">DEMO</span>
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
          <span className="text-slate-700">|</span>
          <span>{points.reduce((sum, p) => sum + p.count, 0)} stories tracked</span>
          <span className="text-slate-700">|</span>
          <span>{points.length} locations</span>
        </div>
      </div>
    </main>
  );
}
