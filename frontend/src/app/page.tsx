"use client";

import { useState, useCallback, useRef } from "react";
import dynamic from "next/dynamic";
import { Topic, GlobePoint, NewsArticle, PanelEntry, PanelFilters, PanelQuery } from "@/types/news";
import { fetchClusterArticles, fetchClusterSummary } from "@/lib/api";
import { applyPage, FIRST_PAGE_LIMIT, nextPage } from "@/lib/loadMore";
import { MAX_PANELS, panelQuery, samePanelQuery } from "@/lib/panelQuery";
import { DEFAULT_WINDOW, sameWindow, type TimeWindow } from "@/lib/timeWindow";
import { useAgent } from "@/hooks/useAgent";
import { useGlobePoints } from "@/hooks/useGlobePoints";
import { useMotionPrefs } from "@/hooks/useMotionPrefs";
import { useSidePanel } from "@/hooks/useSidePanel";
import { useKeepFocus } from "@/hooks/useKeepFocus";
import type { Citation, GlobeAction } from "@/hooks/useAgent";
import BottomBar from "@/components/BottomBar";
import LayerSwitcher, { type GlobeLayer } from "@/components/LayerSwitcher";
import TimelineCapsule from "@/components/TimelineCapsule";
import NewsPanel from "@/components/NewsPanel";
import RecentPlaces from "@/components/RecentPlaces";
import TopBar from "@/components/TopBar";
import AgentPanel from "@/components/AgentPanel";
import SidePanel from "@/components/SidePanel";
import Sky from "@/components/Sky";
import OrbitRings from "@/components/OrbitRings";
import type { GlobeControls } from "@/components/Globe";

// Globe requires `window` — load without SSR
const Globe = dynamic(() => import("@/components/Globe"), { ssr: false });

export default function Home() {
  const [activeTopic, setActiveTopic] = useState<Topic>("All");

  // One time window for the globe, the panels and the timeline (lib/timeWindow).
  const [timeWindow, setTimeWindow] = useState<TimeWindow>(DEFAULT_WINDOW);
  // The dots for the window, filtered to the topic on the client (same array until either changes)
  const { points, error: apiError, loading } = useGlobePoints(timeWindow, activeTopic);
  const [layer, setLayer] = useState<GlobeLayer>("dots");

  const [panelQueue, setPanelQueue] = useState<PanelEntry[]>([]);
  const [expandedPanelId, setExpandedPanelId] = useState<string | null>(null);

  // Side panel (Co-pilot | Stories): open by default on wide screens
  const side = useSidePanel();
  const { showStories } = side;
  // Minimize and close remove the focused control: keep focus in the Stories tab.
  const storiesRef = useRef<HTMLDivElement>(null);
  const keepStoriesFocus = useKeepFocus(storiesRef);

  const globeControlsRef = useRef<GlobeControls | null>(null);

  // Reduced motion and low-power mode (also sets .low-power on <html>)
  const { reduced, lowPower } = useMotionPrefs();
  const getGlobeGeometry = useCallback(() => globeControlsRef.current?.getGeometry() ?? null, []);
  // Intensity is computed per vertex for every place: too slow for a low-power
  // device without WebGPU, and three-globe can't tell us cheaply if it has it.
  const globeLayer: GlobeLayer = lowPower ? "dots" : layer;

  // The same window again (a preset clicked twice) keeps its dots: no refetch.
  const changeWindow = useCallback((next: TimeWindow) => {
    setTimeWindow((prev) => (sameWindow(prev, next) ? prev : next));
  }, []);

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

  // Panels read only their own query, fixed at click time (see panelQuery).
  const fetchPanelData = useCallback(
    async (panelId: string, point: GlobePoint, query: PanelQuery) => {
      try {
        const apiArticles = await fetchClusterArticles(
          point.lat,
          point.lng,
          0.75,
          query.topic,
          point.locationName,
          0,
          FIRST_PAGE_LIMIT,
          query.startTime,
          query.endTime,
        );
        const page = applyPage(
          { articles: [], count: point.count },
          mapArticles(apiArticles),
          0,
          FIRST_PAGE_LIMIT,
        );
        updatePanel(panelId, {
          articles: page.articles,
          nextOffset: page.nextOffset,
          point: { ...point, articles: page.articles, count: page.count },
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
          query.topic,
          query.startTime,
          query.endTime,
        );
        updatePanel(panelId, { clusterSummary: result.summary, summaryLoading: false });
      } catch {
        updatePanel(panelId, { summaryLoading: false });
      }
    },
    [updatePanel],
  );

  const handleLoadMore = useCallback(
    async (panelId: string, filters?: PanelFilters) => {
      const panel = panelQueue.find((p) => p.panelId === panelId);
      if (!panel || panel.loadingMore) return;

      updatePanel(panelId, { loadingMore: true });

      const { query } = panel;
      const isFiltered =
        filters && (filters.sentiment || filters.search || filters.topics.length > 0);

      try {
        // In-panel filters work on the loaded stories, so they get bigger
        // pages. Load more stays while pages come back full; a short page
        // ends the list (see applyPage).
        const { offset, limit } = nextPage(panel.nextOffset, Boolean(isFiltered));
        const apiArticles = await fetchClusterArticles(
          panel.point.lat,
          panel.point.lng,
          0.75,
          query.topic,
          panel.point.locationName,
          offset,
          limit,
          query.startTime,
          query.endTime,
        );
        const page = applyPage(
          { articles: panel.articles, count: panel.point.count },
          mapArticles(apiArticles),
          offset,
          limit,
        );
        updatePanel(panelId, {
          articles: page.articles,
          nextOffset: page.nextOffset,
          point: { ...panel.point, articles: page.articles, count: page.count },
          loadingMore: false,
        });
      } catch {
        updatePanel(panelId, { loadingMore: false });
      }
    },
    [panelQueue, updatePanel],
  );

  const handlePointClick = useCallback(
    (point: GlobePoint) => {
      // Reopen a panel only if it shows this cell for the same topic and
      // window; point ids are list positions, so they can name another cell.
      const query = panelQuery(activeTopic, timeWindow, Date.now());
      const existing = panelQueue.find(
        (p) =>
          p.point.lat === point.lat && p.point.lng === point.lng && samePanelQuery(p.query, query),
      );
      showStories();
      if (existing) {
        setExpandedPanelId(existing.panelId);
        return;
      }

      const panelId = `${point.id}-${Date.now()}`;
      const newEntry: PanelEntry = {
        panelId,
        point,
        query,
        articles: [],
        nextOffset: 0,
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
      fetchPanelData(panelId, point, query);
    },
    [panelQueue, activeTopic, timeWindow, fetchPanelData, showStories],
  );

  const handleZoomChange = useCallback(() => {}, []);

  const handleClosePanel = useCallback(
    (panelId: string) => {
      // Focus goes to the open place's pill, or to the tab when it was this one.
      keepStoriesFocus(panelId === expandedPanelId ? null : expandedPanelId);
      setPanelQueue((prev) => prev.filter((p) => p.panelId !== panelId));
      setExpandedPanelId((prev) => (prev === panelId ? null : prev));
    },
    [expandedPanelId, keepStoriesFocus],
  );

  const handleMinimizePanel = useCallback(
    (panelId: string) => {
      keepStoriesFocus(panelId); // the place stays in Recent places
      setExpandedPanelId(null);
    },
    [keepStoriesFocus],
  );

  const handleExpandPanel = useCallback((panelId: string) => {
    setExpandedPanelId(panelId);
  }, []);

  const handleFiltersChange = useCallback(
    (panelId: string, filters: PanelFilters, filterSummary: string | null) => {
      updatePanel(panelId, { filters, filterSummary });
    },
    [updatePanel],
  );

  // Stories tab: the open places, then the active place's stories
  const expandedPanel = panelQueue.find((p) => p.panelId === expandedPanelId) ?? null;
  const storiesTab = (
    <>
      <RecentPlaces
        places={panelQueue}
        activeId={expandedPanelId}
        onSelect={handleExpandPanel}
        onClose={handleClosePanel}
      />
      {expandedPanel ? (
        <NewsPanel
          key={expandedPanel.panelId}
          point={{ ...expandedPanel.point, articles: expandedPanel.articles }}
          onClose={() => handleClosePanel(expandedPanel.panelId)}
          onMinimize={() => handleMinimizePanel(expandedPanel.panelId)}
          onLoadMore={(filters) => handleLoadMore(expandedPanel.panelId, filters)}
          loadingMore={expandedPanel.loadingMore}
          clusterSummary={expandedPanel.clusterSummary}
          summaryLoading={expandedPanel.summaryLoading}
          articlesLoading={expandedPanel.articlesLoading}
          savedFilters={expandedPanel.filters}
          savedFilterSummary={expandedPanel.filterSummary}
          onFiltersChange={(filters, filterSummary) =>
            handleFiltersChange(expandedPanel.panelId, filters, filterSummary)
          }
        />
      ) : (
        <p className="side-empty">
          {panelQueue.length > 0
            ? "Pick a place above, or click a dot on the globe."
            : "Click a dot on the globe to see its stories here."}
        </p>
      )}
    </>
  );

  return (
    <main className="relative h-screen w-screen overflow-hidden">
      {/* Starfield, under everything */}
      <Sky />

      {/* Globe */}
      <Globe
        points={points}
        onPointClick={handlePointClick}
        onZoomChange={handleZoomChange}
        onReady={(controls) => {
          globeControlsRef.current = controls;
        }}
        reduced={reduced}
        lowPower={lowPower}
        layer={globeLayer}
      />

      {/* Orbital rings around the globe */}
      <OrbitRings getGeometry={getGlobeGeometry} reduced={reduced} lowPower={lowPower} />

      {/* Top bar: brand, topics, status and About in one grid */}
      <TopBar
        activeTopic={activeTopic}
        onTopicChange={setActiveTopic}
        isLive={!apiError && !loading && timeWindow.kind === "live"}
        isLoading={loading}
        isOffline={apiError}
      />

      {/* Co-pilot and stories, right (a bottom sheet below 1180px) */}
      <SidePanel
        tab={side.tab}
        onTabChange={side.setTab}
        open={side.open}
        onOpenChange={side.setOpen}
        storiesCount={panelQueue.length}
        storiesRef={storiesRef}
        copilot={
          <AgentPanel
            messages={agentMessages}
            isLoading={agentLoading}
            isDisabled={agentDisabled}
            activeTools={activeTools}
            onAsk={agentAsk}
            onStop={agentStop}
            onClear={agentClear}
            onCitationClick={handleCitationClick}
          />
        }
        stories={storiesTab}
      />

      {/* Bottom row: layers and the timeline. After the side panel: the CSS
          keeps it clear of the panel, and above the sheet, by sibling selectors. */}
      <BottomBar>
        <LayerSwitcher
          layer={globeLayer}
          onChange={setLayer}
          unavailable={lowPower ? { intensity: "Intensity is off in low-power mode" } : undefined}
        />
        <TimelineCapsule
          timeWindow={timeWindow}
          onChange={changeWindow}
          stories={points.reduce((sum, p) => sum + p.count, 0)}
          places={points.length}
          reduced={reduced}
        />
      </BottomBar>
    </main>
  );
}
