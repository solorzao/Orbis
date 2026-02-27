"use client";

import { useState, useMemo, useCallback } from "react";
import dynamic from "next/dynamic";
import { Topic, GlobePoint } from "@/types/news";
import { mockArticles } from "@/lib/mockData";
import { clusterArticles } from "@/lib/clustering";
import NewsPanel from "@/components/NewsPanel";
import TopicFilter from "@/components/TopicFilter";

// Globe requires `window` — load without SSR
const Globe = dynamic(() => import("@/components/Globe"), { ssr: false });

export default function Home() {
  const [activeTopic, setActiveTopic] = useState<Topic>("All");
  const [selectedPoint, setSelectedPoint] = useState<GlobePoint | null>(null);
  const [altitude, setAltitude] = useState(2.5);

  // Filter articles by topic
  const filteredArticles = useMemo(() => {
    if (activeTopic === "All") return mockArticles;
    return mockArticles.filter((a) => a.topicTags.includes(activeTopic));
  }, [activeTopic]);

  // Cluster articles based on zoom level
  const points = useMemo(
    () => clusterArticles(filteredArticles, altitude),
    [filteredArticles, altitude]
  );

  const handlePointClick = useCallback((point: GlobePoint) => {
    setSelectedPoint(point);
  }, []);

  const handleZoomChange = useCallback((alt: number) => {
    setAltitude(alt);
  }, []);

  const handleClosePanel = useCallback(() => {
    setSelectedPoint(null);
  }, []);

  return (
    <main className="relative h-screen w-screen overflow-hidden bg-[#030712]">
      {/* Globe */}
      <Globe
        points={points}
        onPointClick={handlePointClick}
        onZoomChange={handleZoomChange}
      />

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
              background: "radial-gradient(circle at 30% 30%, rgba(255,255,255,0.2), transparent 60%)",
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
      <NewsPanel point={selectedPoint} onClose={handleClosePanel} />

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
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
            </span>
            LIVE
          </span>
          <span className="text-slate-700">|</span>
          <span>{filteredArticles.length} stories tracked</span>
          <span className="text-slate-700">|</span>
          <span>{points.length} locations</span>
        </div>
      </div>
    </main>
  );
}
