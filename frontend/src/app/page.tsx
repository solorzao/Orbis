"use client";

import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import dynamic from "next/dynamic";
import type {
  ArticleThread,
  CountryLink,
  GlobePoint,
  LinkEntry,
  PanelEntry,
  PanelFilters,
  PanelQuery,
  Topic,
} from "@/types/news";
import { fetchClusterArticles, fetchClusterSummary, fetchLinkDetail } from "@/lib/api";
import { apiArticlesToNewsArticles } from "@/lib/clustering";
import { applyPage, FIRST_PAGE_LIMIT, nextPage } from "@/lib/loadMore";
import { panelQuery, queryWindow, recentToEvict, samePanelQuery } from "@/lib/panelQuery";
import { cardLabel } from "@/lib/hoverCard";
import { cellKey, dotInCell, pointAt } from "@/lib/cells";
import { focusCentre, trackAnnouncement, type EntityPlace, type EntityRef } from "@/lib/entities";
import { DEFAULT_WINDOW, sameWindow, type TimeWindow } from "@/lib/timeWindow";
import { breakingDot, type BreakingStory } from "@/lib/breaking";
import {
  readSinceDismissed,
  sinceDot,
  sinceRange,
  writeSinceDismissed,
  type SincePlace,
} from "@/lib/sinceVisit";
import {
  actionCountries,
  linkKey,
  linkedCountries,
  linkPill,
  linksStatus,
  toLinkDetail,
  type LinkRank,
} from "@/lib/links";
import {
  THREAD_PAGE,
  fetchThread,
  replayAnnouncement,
  threadsStatus,
  toThreadArticles,
  type ThreadArticle,
  type ThreadDetail,
} from "@/lib/threads";
import { isWebUrl, useAgent } from "@/hooks/useAgent";
import { useGlobePoints } from "@/hooks/useGlobePoints";
import { useLinks } from "@/hooks/useLinks";
import { useLinkExplain } from "@/hooks/useLinkExplain";
import { useBreaking } from "@/hooks/useBreaking";
import { useLastVisit } from "@/hooks/useLastVisit";
import { useDelta } from "@/hooks/useDelta";
import { useMotionPrefs } from "@/hooks/useMotionPrefs";
import { useSidePanel, useWideScreen, type SideTab } from "@/hooks/useSidePanel";
import { useThread, useThreads } from "@/hooks/useThreads";
import { useSpreadReplay } from "@/hooks/useSpreadReplay";
import { useFlyToThread, type ThreadView } from "@/hooks/useFlyToThread";
import { useKeepFocus } from "@/hooks/useKeepFocus";
import { useEntity } from "@/hooks/useEntity";
import { useHoverCard, useTouchOnly } from "@/hooks/useHoverCard";
import { rememberBrief, useHoverPreview } from "@/hooks/useHoverPreview";
import type { Citation, GlobeAction } from "@/hooks/useAgent";
import BottomBar from "@/components/BottomBar";
import LayerSwitcher, { type GlobeLayer } from "@/components/LayerSwitcher";
import TimelineCapsule from "@/components/TimelineCapsule";
import NewsPanel from "@/components/NewsPanel";
import LinkInspector from "@/components/LinkInspector";
import LinkList from "@/components/LinkList";
import RecentPlaces from "@/components/RecentPlaces";
import TopBar from "@/components/TopBar";
import CoPilot from "@/components/CoPilot";
import SidePanel from "@/components/SidePanel";
import Sky from "@/components/Sky";
import OrbitRings from "@/components/OrbitRings";
import GlobeHud from "@/components/GlobeHud";
import HoverCard from "@/components/HoverCard";
import ArcPill from "@/components/ArcPill";
import LinksChip from "@/components/LinksChip";
import BreakingTicker from "@/components/BreakingTicker";
import SinceStrip from "@/components/SinceStrip";
import ThreadsRail, { type ThreadRef } from "@/components/ThreadsRail";
import ThreadStories from "@/components/ThreadStories";
import TrackSearch from "@/components/TrackSearch";
import EntityDossier from "@/components/EntityDossier";
import Board from "@/components/Board";
import BoardMergePrompt from "@/components/BoardMergePrompt";
import { PinContext, type PinControls } from "@/components/PinButton";
import { useBoard } from "@/hooks/useBoard";
import {
  useBoardLinks,
  useBoardMemo,
  useBoardMirror,
  useBoardRefresh,
  useSharedBoard,
} from "@/hooks/useBoardData";
import { boardEdges } from "@/lib/boardEdges";
import type { GlobeControls, GlobeFocus } from "@/components/Globe";

/** The tracked entity's dossier among the Inspect tab's places and links. */
const ENTITY_ID = "entity";

/** Whether a key press is typing (in a field), where "/" and Escape aren't the page's. */
const isTyping = (target: EventTarget | null) =>
  target instanceof HTMLElement &&
  (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));

/** A thread's stories in Inspect ("All {n} stories"). */
interface ThreadStoriesEntry {
  id: number;
  title: string;
  total: number;
  articles: ThreadArticle[];
  nextOffset: number;
  /** The last page was full. */
  hasMore: boolean;
  loadingMore: boolean;
}

// Globe requires `window` — load without SSR
const Globe = dynamic(() => import("@/components/Globe"), { ssr: false });

export default function Home() {
  const [activeTopic, setActiveTopic] = useState<Topic>("All");

  // One time window for the globe, the panels and the timeline (lib/timeWindow).
  const [timeWindow, setTimeWindow] = useState<TimeWindow>(DEFAULT_WINDOW);
  // The dots for the window and topic, filtered on the server (same array until new dots land)
  const { points, error: apiError, loading } = useGlobePoints(timeWindow, activeTopic);
  const [layer, setLayer] = useState<GlobeLayer>("dots");
  // The Links overlay: co-coverage arcs over either base layer, ranked by lift or count.
  const [linksOn, setLinksOn] = useState(false);
  const [linkRank, setLinkRank] = useState<LinkRank>("lift");
  const linksResult = useLinks(timeWindow, activeTopic, linkRank, linksOn);
  const { links } = linksResult;
  // Said when Links draws nothing: an empty window, or links that failed to load.
  const linksNote = linksStatus({ on: linksOn, ...linksResult });
  // The arc under the pointer, named by the arc pill.
  const [hoveredLink, setHoveredLink] = useState<CountryLink | null>(null);
  // The timeline's replay: the status pill says Replay rather than flashing each step's load.
  const [replaying, setReplaying] = useState(false);
  // What is breaking now, for the topic: only for a live window (a range or a
  // replay looks back), polled every 5 minutes. The ticker and the rings show it.
  const breaking = useBreaking(activeTopic, timeWindow.kind === "live" && !replaying);
  // Since your last visit: the visit before this one (localStorage), what
  // changed since (asked when it was 1 h to 7 days ago), and Dismiss (the session).
  const lastVisit = useLastVisit();
  const sinceDelta = useDelta(lastVisit);
  const [sinceDismissed, setSinceDismissed] = useState(readSinceDismissed);

  // What the Inspect tab holds: places (their stories) and links, up to
  // MAX_PANELS together, and the one shown (a panelId or a linkId).
  const [panelQueue, setPanelQueue] = useState<PanelEntry[]>([]);
  const [linkQueue, setLinkQueue] = useState<LinkEntry[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);

  // Side panel (Co-pilot | Inspect, and Threads below 1180px): open by default on wide screens
  const side = useSidePanel();
  // The investigation board: its split view from 1180px, a list in the sheet below.
  // Anything opened in Inspect closes it (the globe shows one focus at a time).
  const [boardOpen, setBoardOpen] = useState(false);
  const { showInspect: showSideInspect } = side;
  const showInspect = useCallback(() => {
    setBoardOpen(false);
    showSideInspect();
  }, [showSideInspect]);
  // From 1180px Threads is a rail in the left column; below, a tab in the sheet.
  const wide = useWideScreen();
  const sideTab = wide && side.tab === "threads" ? "copilot" : side.tab;

  // The Threads overlay: the window's developing stories (live windows only),
  // and the selected one's spread. Below 1180px its tab lists them too.
  const [threadsOn, setThreadsOn] = useState(false);
  const [selectedThread, setSelectedThread] = useState<ThreadRef | null>(null);
  const threadsResult = useThreads(
    timeWindow,
    activeTopic,
    threadsOn || (!wide && sideTab === "threads" && side.open === true),
  );
  const threadsNote = threadsStatus({
    on: threadsOn || (!wide && sideTab === "threads"),
    live: timeWindow.kind === "live",
    ...threadsResult,
  });
  // The selected thread's detail, and its spread: the list's places until the detail lands.
  // A thread merged into another answers as it: select that one, so its row and links show.
  const adoptMergedThread = useCallback(
    (id: number) => setSelectedThread((t) => (t ? { ...t, id } : t)),
    [],
  );
  const { detail: threadDetail } = useThread(selectedThread?.id ?? null, adoptMergedThread);
  const selectedId = selectedThread?.id ?? null;
  const listedThread = threadsResult.threads.find((t) => t.id === selectedId);
  const spread = threadDetail?.spread ?? listedThread?.places;
  const globeThread = useMemo(
    () => (selectedId !== null && spread ? { id: selectedId, spread } : null),
    [selectedId, spread],
  );

  // The entity tracker: the person or organisation tracked (one at a time),
  // its dossier, and the globe's focus mode on its places once that lands.
  const [tracked, setTracked] = useState<EntityRef | null>(null);
  const entity = useEntity(tracked);
  const { dossier } = entity;
  const globeFocus = useMemo<GlobeFocus | null>(
    () =>
      dossier && dossier.places.length > 0
        ? { key: dossier.name, places: dossier.places, centre: focusCentre(dossier.places) }
        : null,
    [dossier],
  );
  // What the page's announcer says of it, and of the Track search's results.
  const trackNote = trackAnnouncement({ tracked, ...entity });
  const [searchNote, setSearchNote] = useState("");
  // Below 1180px the top bar's search button opens the Track search in the sheet.
  const [sheetSearch, setSheetSearch] = useState(false);
  const barSearchRef = useRef<HTMLInputElement>(null);
  const sheetInputRef = useRef<HTMLInputElement>(null);
  const searchButtonRef = useRef<HTMLButtonElement>(null);
  const sheetSearchRef = useRef<HTMLDivElement>(null);
  // Minimize and close remove the focused control: keep focus in the Inspect tab.
  const inspectRef = useRef<HTMLDivElement>(null);
  const copilotRef = useRef<HTMLDivElement>(null);
  const topicsRef = useRef<HTMLElement>(null);
  const keepInspectFocus = useKeepFocus(inspectRef);
  // "All {n} stories" in the sheet's Threads tab hides it: focus goes on to Inspect.
  const threadsTabRef = useRef<HTMLDivElement>(null);
  const keepThreadsFocus = useKeepFocus(inspectRef, threadsTabRef);
  // A choice in the sheet's search closes it: the focus goes on to what opened.
  const keepSearchInspectFocus = useKeepFocus(inspectRef, sheetSearchRef);
  const keepSearchThreadsFocus = useKeepFocus(threadsTabRef, sheetSearchRef);

  const globeControlsRef = useRef<GlobeControls | null>(null);
  const playRef = useRef<HTMLButtonElement>(null);

  // Reduced motion and low-power mode (also sets .low-power on <html>)
  const { reduced, lowPower } = useMotionPrefs();
  // "Replay how {title} spread": the selected thread's places lit in order of first report.
  const spreadReplay = useSpreadReplay(globeThread?.spread.length ?? 0, reduced);
  const { reset: resetSpreadReplay } = spreadReplay;
  const getGlobeGeometry = useCallback(() => globeControlsRef.current?.getGeometry() ?? null, []);
  // Intensity is off in low-power mode: its heatmap is computed at ~246k vertices,
  // about 0.75 s on a slow CPU even with WebGPU and seconds without it (see
  // heatmapPoints and webGpuReady, which probes for a device only once it's shown).
  const globeLayer: GlobeLayer = lowPower ? "dots" : layer;

  // City hover card: shown for the dot under the pointer (or tapped, on touch
  // screens), with its dwell data (sparkline, names, cached brief) after 400 ms.
  const touch = useTouchOnly();
  const hoverCardRef = useRef<HTMLElement>(null);
  const hover = useHoverCard(touch, hoverCardRef, points);
  const { preview, loading: previewLoading } = useHoverPreview(
    hover.focus,
    timeWindow,
    activeTopic,
  );
  const projectPoint = useCallback(
    (lat: number, lng: number, altitude?: number) =>
      globeControlsRef.current?.project(lat, lng, altitude) ?? null,
    [],
  );
  // Conflict images the visitor chose to see: kept for the session, never stored.
  const [revealed, setRevealed] = useState<ReadonlySet<string>>(() => new Set());
  const revealImage = useCallback(
    (url: string) => setRevealed((prev) => new Set(prev).add(url)),
    [],
  );

  // The same window again (a preset clicked twice) keeps its dots: no refetch.
  // A range (or a day replay's) has no threads: the selected one and its arcs go.
  const changeWindow = useCallback((next: TimeWindow) => {
    setTimeWindow((prev) => (sameWindow(prev, next) ? prev : next));
  }, []);

  // A range the visitor chose has no threads (they follow the live windows):
  // the selected one and its arcs go. A day replay's days don't count: a
  // thread selected then stops the replay (TimelineCapsule) instead.
  const handleWindowChosen = useCallback(
    (next: TimeWindow) => {
      if (next.kind === "live") return;
      resetSpreadReplay();
      setSelectedThread(null);
    },
    [resetSpreadReplay],
  );

  // A thread selected: the globe goes to the middle of its places, framing them
  // (spreadView), at once with reduced motion; once per selection, and not
  // after the visitor has turned the globe themselves (useFlyToThread).
  const grabsRef = useRef(0);
  const handleGrab = useCallback(() => {
    grabsRef.current += 1;
  }, []);
  const flyToThread = useCallback(
    (view: ThreadView) =>
      globeControlsRef.current?.flyTo(view.lat, view.lng, view.altitude, reduced ? 0 : undefined),
    [reduced],
  );
  useFlyToThread(selectedId, globeThread?.spread, flyToThread, grabsRef);

  const handleGlobeAction = useCallback((action: GlobeAction) => {
    globeControlsRef.current?.flyTo(action.lat, action.lng, 2.0);
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
    if (isWebUrl(citation.url)) {
      window.open(citation.url, "_blank", "noopener,noreferrer");
    }
  }, []);

  const updatePanel = useCallback((panelId: string, updates: Partial<PanelEntry>) => {
    setPanelQueue((prev) => prev.map((p) => (p.panelId === panelId ? { ...p, ...updates } : p)));
  }, []);

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
          apiArticlesToNewsArticles(apiArticles),
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
        // The place's hover card shows it as its brief from now on.
        rememberBrief(point, queryWindow(query), query.topic ?? "All", result.summary);
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
          apiArticlesToNewsArticles(apiArticles),
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
      showInspect();
      if (existing) {
        setActiveId(existing.panelId);
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

      // The oldest place or link closes to make room (MAX_PANELS in all).
      const evict = recentToEvict(panelQueue, linkQueue);
      setPanelQueue((prev) => [...prev.filter((p) => p.panelId !== evict), newEntry]);
      if (evict) setLinkQueue((prev) => prev.filter((l) => l.linkId !== evict));

      setActiveId(panelId);
      fetchPanelData(panelId, point, query);
    },
    [panelQueue, linkQueue, activeTopic, timeWindow, fetchPanelData, showInspect],
  );

  // A breaking story: fly to its place and open it in Inspect, by its cell's
  // dot, or a stand-in when the globe has none there (breakingDot).
  const handleBreakingOpen = useCallback(
    (story: BreakingStory) => {
      globeControlsRef.current?.flyTo(story.lat, story.lng, 1.5);
      handlePointClick(breakingDot(points, story));
    },
    [points, handlePointClick],
  );

  // Show: the window from the last visit (floored, as the strip counts it) to now.
  const handleSinceShow = useCallback(() => {
    if (lastVisit === null) return;
    const range = sinceRange(lastVisit, Date.now());
    changeWindow(range);
    handleWindowChosen(range);
  }, [lastVisit, changeWindow, handleWindowChosen]);

  // A place new since the visit: fly there and open it, as a breaking story.
  const handleSinceOpen = useCallback(
    (place: SincePlace) => {
      globeControlsRef.current?.flyTo(place.lat, place.lng, 1.5);
      handlePointClick(sinceDot(points, place));
    },
    [points, handlePointClick],
  );

  // Dismiss takes its control away: focus goes on to the topic pills beside
  // the strip, or stays in the co-pilot that held the callout.
  const handleSinceDismiss = useCallback((variant: "strip" | "callout") => {
    if (variant === "strip") topicsRef.current?.querySelector("button")?.focus();
    else copilotRef.current?.focus();
    writeSinceDismissed();
    setSinceDismissed(true);
  }, []);

  // Threads on shows the rail (from 1180px) or the sheet's Threads tab (below,
  // where the rail has no room); off forgets the selected thread and its arcs.
  const { setTab: setSideTab, setOpen: setSideOpen } = side;
  const handleThreadsChange = useCallback(
    (on: boolean) => {
      setThreadsOn(on);
      if (!on) {
        resetSpreadReplay();
        setSelectedThread(null);
      }
      if (on && !wide) {
        setBoardOpen(false); // the sheet's Threads tab, not the board's list
        setSideTab("threads");
        setSideOpen(true);
      }
    },
    [wide, setSideTab, setSideOpen, resetSpreadReplay],
  );

  // Tracking ends: the dossier goes from Inspect, and the globe's focus mode.
  const endTracking = useCallback(() => {
    setTracked(null);
    setActiveId((prev) => (prev === ENTITY_ID ? null : prev));
  }, []);

  // A row selects its thread (Threads on, for the sheet's tab); the selected one
  // again closes it. A thread's arcs and an inspected link's highlight don't
  // show together: the link's comes back when the thread closes. The globe
  // shows one focus at a time: a thread selected stops tracking an entity, as
  // tracking one closes the selected thread.
  const handleThreadSelect = useCallback(
    (thread: ThreadRef | null) => {
      resetSpreadReplay();
      setSelectedThread(thread);
      if (thread) {
        setThreadsOn(true);
        endTracking();
        setBoardOpen(false);
      }
    },
    [resetSpreadReplay, endTracking],
  );

  // A story's "Part of" chip (or a thread found by the Track search): Threads
  // on, its thread selected and its spread drawn; below 1180px the sheet shows
  // it in the Threads tab.
  const handleThreadChip = useCallback(
    (thread: Pick<ArticleThread, "id" | "title">) => {
      handleThreadSelect({ id: thread.id, title: thread.title });
      if (!wide) {
        setSideTab("threads");
        setSideOpen(true);
      }
    },
    [handleThreadSelect, wide, setSideTab, setSideOpen],
  );

  // Track a person or organisation (from the search, a pill or the dossier's
  // constellation): its dossier in Inspect and the globe's focus mode. The
  // selected thread's arcs go, and the hover card that offered the name.
  const { dismiss: dismissHoverCard } = hover;
  const handleTrack = useCallback(
    (next: EntityRef) => {
      resetSpreadReplay();
      setSelectedThread(null);
      // The same name again keeps its dossier: no new request.
      setTracked((prev) => (prev?.name === next.name && prev.type === next.type ? prev : next));
      setActiveId(ENTITY_ID);
      showInspect();
      dismissHoverCard();
    },
    [resetSpreadReplay, showInspect, dismissHoverCard],
  );
  // A thread's key entities don't say person or org: useEntity tries both.
  const handleTrackName = useCallback((name: string) => handleTrack({ name }), [handleTrack]);

  // A place from the Track search or the dossier: fly there (at once with
  // reduced motion) and open it, as a click on its dot does.
  const handlePlaceOpen = useCallback(
    (point: GlobePoint) => {
      globeControlsRef.current?.flyTo(point.lat, point.lng, 1.5, reduced ? 0 : undefined);
      handlePointClick(point);
    },
    [reduced, handlePointClick],
  );
  const handleEntityPlace = useCallback(
    (place: EntityPlace) =>
      handlePlaceOpen(
        dotInCell(points, { lat: place.lat, lng: place.lng, place: place.place, count: place.n }),
      ),
    [points, handlePlaceOpen],
  );

  // The search button (below 1180px) opens the Track search in the sheet, or closes it.
  const handleSearchOpen = useCallback(() => {
    setSheetSearch((open) => !open);
    setBoardOpen(false);
    setSideOpen(true);
  }, [setSideOpen]);
  const closeSheetSearch = useCallback(() => {
    setSheetSearch(false);
    searchButtonRef.current?.focus();
  }, []);
  // The search (or the board's list) has the sheet while it is open: a tab picked closes it.
  const handleSideTab = useCallback(
    (tab: SideTab) => {
      setSheetSearch(false);
      setBoardOpen(false);
      setSideTab(tab);
    },
    [setSideTab],
  );
  // A choice in the sheet's search closes it; the focus follows to what opened
  // (the place or dossier in Inspect, or the thread in the Threads tab).
  const sheetChoice = useCallback(
    (into: "inspect" | "threads") => {
      if (into === "inspect") keepSearchInspectFocus(null);
      else keepSearchThreadsFocus(null);
      setSheetSearch(false);
    },
    [keepSearchInspectFocus, keepSearchThreadsFocus],
  );
  const searchHandlers = (variant: "bar" | "sheet") => ({
    points,
    onPlace: (point: GlobePoint) => {
      if (variant === "sheet") sheetChoice("inspect");
      handlePlaceOpen(point);
    },
    onEntity: (next: EntityRef) => {
      if (variant === "sheet") sheetChoice("inspect");
      handleTrack(next);
    },
    onThread: (thread: { id: number; title: string }) => {
      if (variant === "sheet") sheetChoice("threads");
      handleThreadChip(thread);
    },
    onAnnounce: setSearchNote,
  });

  // The investigation board (localStorage): pins from the panels, the board's
  // view of them with their edges and memo, and the globe's mirror of it.
  const board = useBoard();
  const [boardNote, setBoardNote] = useState("");
  const boardButtonRef = useRef<HTMLButtonElement>(null);
  // Shown: the split view from 1180px, or the list while the sheet is open below.
  const boardShown = boardOpen && (wide || side.open === true);
  // Opening it ends the globe's other focus (a selected thread, a tracked entity).
  const openBoard = useCallback(() => {
    resetSpreadReplay();
    setSelectedThread(null);
    endTracking();
    dismissHoverCard();
    setSheetSearch(false);
    setBoardOpen(true);
    if (!wide) setSideOpen(true);
  }, [resetSpreadReplay, endTracking, dismissHoverCard, wide, setSideOpen]);
  // Closed by its button or Escape: the focus goes back to the Board button.
  const closeBoard = useCallback(() => {
    setBoardOpen(false);
    boardButtonRef.current?.focus();
  }, []);
  const toggleBoard = useCallback(
    () => (boardShown ? closeBoard() : openBoard()),
    [boardShown, closeBoard, openBoard],
  );
  const { has: pinned, full: boardFull, toggle: togglePin, unpin } = board;
  const pinControls = useMemo<PinControls>(
    () => ({
      has: pinned,
      full: boardFull,
      toggle: (item, snapshot) => {
        const done = togglePin(item, snapshot);
        setBoardNote(
          done === "pinned"
            ? `Pinned to the board: ${snapshot.title}.`
            : done === "unpinned"
              ? `Removed from the board: ${snapshot.title}.`
              : "The board is full: remove a pin to add another.",
        );
      },
    }),
    [pinned, boardFull, togglePin],
  );
  const boardItems = useMemo(() => board.pins.map((p) => p.item), [board.pins]);
  const boardLinks = useBoardLinks(boardItems, boardShown);
  const edges = useMemo(
    () => boardEdges(boardLinks.edges, board.pins),
    [boardLinks.edges, board.pins],
  );
  const boardMirror = useBoardMirror(board.pins, edges, boardShown);
  const boardMemo = useBoardMemo(board.pins);
  useBoardRefresh(boardShown, board, setBoardNote);
  const sharedBoard = useSharedBoard(board, { onOpen: openBoard, announce: setBoardNote });
  const handleUnpin = useCallback(
    (item: string) => {
      unpin(item);
      setBoardNote("Removed from the board.");
    },
    [unpin],
  );
  const boardView = (variant: "split" | "sheet") => (
    <Board
      variant={variant}
      pins={board.pins}
      edges={edges}
      coCoverageChecked={boardLinks.coCoverageChecked}
      edgesFailed={boardLinks.failed}
      memo={boardMemo.memo}
      analyzing={boardMemo.analyzing}
      onAnalyze={boardMemo.analyze}
      onDismissMemo={boardMemo.dismiss}
      onMove={board.move}
      onRemove={handleUnpin}
      onClose={closeBoard}
    />
  );

  // "/" focuses the Track search (the mockup's shortcut): the top bar's pill
  // from 1180px, the sheet's below. Escape on the page (nothing focused, no
  // hover card to hide first) closes the board, or stops tracking.
  const hoverShown = hover.card !== null;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === "/") {
        e.preventDefault();
        if (wide) barSearchRef.current?.focus();
        else if (sheetInputRef.current) sheetInputRef.current.focus();
        else {
          setSheetSearch(true); // it opens focused
          setSideOpen(true);
        }
        return;
      }
      const onPage = !document.activeElement || document.activeElement === document.body;
      if (e.key !== "Escape" || !onPage || hoverShown) return;
      if (boardOpen) closeBoard();
      else if (tracked) endTracking();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [wide, tracked, hoverShown, endTracking, setSideOpen, boardOpen, closeBoard]);

  // "All {n} stories": the thread's stories in Inspect, the detail's first page
  // at once, then 20 more a page.
  const [threadStories, setThreadStories] = useState<ThreadStoriesEntry | null>(null);
  const threadStoriesId = threadStories ? `thread-${threadStories.id}` : null;
  const handleShowThreadStories = useCallback(
    (detail: ThreadDetail) => {
      keepThreadsFocus(null);
      setThreadStories({
        id: detail.id,
        title: detail.title,
        total: detail.stories,
        articles: detail.articles,
        nextOffset: detail.articles.length,
        hasMore: detail.articles.length === THREAD_PAGE && detail.articles.length < detail.stories,
        loadingMore: false,
      });
      setActiveId(`thread-${detail.id}`);
      showInspect();
    },
    [showInspect, keepThreadsFocus],
  );
  const handleMoreThreadStories = useCallback(async () => {
    if (!threadStories || threadStories.loadingMore) return;
    const { id, nextOffset } = threadStories;
    // Only into the same thread's list: another may have replaced it meanwhile.
    const update = (f: (s: ThreadStoriesEntry) => ThreadStoriesEntry) =>
      setThreadStories((s) => (s !== null && s.id === id ? f(s) : s));
    update((s) => ({ ...s, loadingMore: true }));
    try {
      const api = await fetchThread({ id, offset: nextOffset });
      const page = toThreadArticles(api.articles);
      update((s) => ({
        ...s,
        articles: [...s.articles, ...page],
        nextOffset: s.nextOffset + page.length,
        hasMore: page.length === THREAD_PAGE,
        loadingMore: false,
      }));
    } catch {
      update((s) => ({ ...s, loadingMore: false }));
    }
  }, [threadStories]);

  const updateLink = useCallback((linkId: string, updates: Partial<LinkEntry>) => {
    setLinkQueue((prev) => prev.map((l) => (l.linkId === linkId ? { ...l, ...updates } : l)));
  }, []);

  // A link reads only its own query, fixed when it was opened, like a panel.
  const fetchLinkData = useCallback(
    async (linkId: string, link: CountryLink, query: PanelQuery) => {
      try {
        const api = await fetchLinkDetail({ a: link.a.iso, b: link.b.iso, query });
        updateLink(linkId, {
          detail: toLinkDetail(api),
          detailLoading: false,
          loadedAt: Date.now(),
        });
      } catch {
        updateLink(linkId, { detailLoading: false, detailError: true });
      }
    },
    [updateLink],
  );

  // An arc's click opens its link in the Inspect tab (or the one already open
  // for the same pair, topic and window).
  const handleLinkOpen = useCallback(
    (link: CountryLink) => {
      // Its highlight, not a thread's arcs or a tracked entity's focus.
      resetSpreadReplay();
      setSelectedThread(null);
      setTracked(null);
      const query = panelQuery(activeTopic, timeWindow, Date.now());
      const key = linkKey(link.a.iso, link.b.iso);
      const existing = linkQueue.find(
        (l) => linkKey(l.link.a.iso, l.link.b.iso) === key && samePanelQuery(l.query, query),
      );
      showInspect();
      if (existing) {
        setActiveId(existing.linkId);
        return;
      }
      const createdAt = Date.now();
      const linkId = `link-${key}-${createdAt}`;
      const entry: LinkEntry = {
        linkId,
        link,
        query,
        detail: null,
        detailLoading: true,
        explanation: null,
        explaining: false,
        createdAt,
      };
      const evict = recentToEvict(panelQueue, linkQueue);
      setLinkQueue((prev) => [...prev.filter((l) => l.linkId !== evict), entry]);
      if (evict) setPanelQueue((prev) => prev.filter((p) => p.panelId !== evict));
      setActiveId(linkId);
      fetchLinkData(linkId, link, query);
    },
    [panelQueue, linkQueue, activeTopic, timeWindow, fetchLinkData, showInspect, resetSpreadReplay],
  );

  // Explain this link: one request per link at a time (useLinkExplain).
  const handleExplain = useLinkExplain(updateLink);

  // A dot's click opens its panel. On a touch screen the first tap shows its
  // hover card instead, and a second tap (or the card's Open stories) opens it.
  const { tap: tapDot, dismiss: dismissCard } = hover;
  const handleDotClick = useCallback(
    (point: GlobePoint) => {
      if (touch) {
        if (tapDot(point)) handlePointClick(point);
        return;
      }
      dismissCard();
      handlePointClick(point);
    },
    [touch, tapDot, dismissCard, handlePointClick],
  );

  // The card's place as the dots have it now (they refresh with the window and
  // topic); a place that is no longer a dot shows no card (useHoverCard hides it).
  const shownCard = hover.card;
  const cardPoint = shownCard
    ? (points.find((p) => p.lat === shownCard.point.lat && p.lng === shownCard.point.lng) ?? null)
    : null;
  // The preview is the focused dot's: the card's only once the pointer is on its place.
  const previewIsCards =
    !!cardPoint &&
    !!hover.focus &&
    cellKey(hover.focus.lat, hover.focus.lng) === cellKey(cardPoint.lat, cardPoint.lng);

  const handleZoomChange = useCallback(() => {}, []);

  // Closing or minimizing works the same for a place, a link and the tracked
  // entity's dossier (by id): closing that stops tracking.
  const handleClosePanel = useCallback(
    (id: string) => {
      // Focus goes to the open pill, or to the tab when it was this one.
      keepInspectFocus(id === activeId ? null : activeId);
      setPanelQueue((prev) => prev.filter((p) => p.panelId !== id));
      setLinkQueue((prev) => prev.filter((l) => l.linkId !== id));
      if (id === threadStoriesId) setThreadStories(null);
      if (id === ENTITY_ID) setTracked(null);
      setActiveId((prev) => (prev === id ? null : prev));
    },
    [activeId, keepInspectFocus, threadStoriesId],
  );
  // Stop tracking (the dossier's button or Escape, or its pill's ×).
  const handleStopTracking = useCallback(() => handleClosePanel(ENTITY_ID), [handleClosePanel]);

  const handleMinimizePanel = useCallback(
    (id: string) => {
      keepInspectFocus(id); // it stays among the recent pills
      setActiveId(null);
    },
    [keepInspectFocus],
  );

  const handleSelectRecent = useCallback((id: string) => {
    setActiveId(id);
  }, []);

  const handleFiltersChange = useCallback(
    (panelId: string, filters: PanelFilters, filterSummary: string | null) => {
      updatePanel(panelId, { filters, filterSummary });
    },
    [updatePanel],
  );

  // Inspect tab: the recent places and links, then the one inspected
  const expandedPanel = panelQueue.find((p) => p.panelId === activeId) ?? null;
  const activeLink = linkQueue.find((l) => l.linkId === activeId) ?? null;
  // The inspected link's highlight, unless a thread's arcs are drawn (one or the other).
  const inspectedLink =
    activeLink && !selectedThread ? linkKey(activeLink.link.a.iso, activeLink.link.b.iso) : null;
  const activeThreadStories = threadStories && activeId === threadStoriesId ? threadStories : null;

  // The arc pill names the hovered arc, else the inspected one, while it is drawn.
  const drawn = (key: string | null) =>
    key === null ? null : (links.find((l) => linkKey(l.a.iso, l.b.iso) === key) ?? null);
  const pillLink =
    drawn(hoveredLink && linkKey(hoveredLink.a.iso, hoveredLink.b.iso)) ?? drawn(inspectedLink);

  // Co-pilot: "Show stories here" takes the click path for the dot at an action's place.
  const showStoriesFor = useCallback(
    (action: GlobeAction) => {
      const point = pointAt(points, action.lat, action.lng);
      return point ? () => handlePointClick(point) : null;
    },
    [points, handlePointClick],
  );
  // Co-pilot: "Show links" turns the Links layer on when an answer's places
  // are in two or more countries (by the globe's dots there) and it is off.
  const showLinksFor = useCallback(
    (actions: GlobeAction[]) =>
      actionCountries(actions, points).length >= 2
        ? { on: linksOn, turnOn: () => setLinksOn(true) }
        : null,
    [linksOn, points],
  );

  // "Since your last visit": under the brand from 1180px, a co-pilot callout below.
  const since = (variant: "strip" | "callout") =>
    sinceDelta && lastVisit !== null && !sinceDismissed ? (
      <SinceStrip
        variant={variant}
        lastVisit={lastVisit}
        delta={sinceDelta}
        onShow={handleSinceShow}
        onOpen={handleSinceOpen}
        onDismiss={() => handleSinceDismiss(variant)}
      />
    ) : null;

  const inspectTab = (
    <>
      <RecentPlaces
        places={panelQueue}
        links={linkQueue}
        entity={tracked ? { id: ENTITY_ID, name: dossier?.name ?? tracked.name } : null}
        activeId={activeId}
        onSelect={handleSelectRecent}
        onClose={handleClosePanel}
      />
      {tracked && activeId === ENTITY_ID ? (
        <EntityDossier
          // A pivot is a new dossier: it starts on its heading (the node pressed went).
          key={`${tracked.type ?? ""}:${tracked.name}`}
          entity={tracked}
          dossier={dossier}
          loading={entity.loading}
          notFound={entity.notFound}
          error={entity.error}
          onPivot={handleTrack}
          onPlace={handleEntityPlace}
          onStop={handleStopTracking}
          onMinimize={() => handleMinimizePanel(ENTITY_ID)}
        />
      ) : activeLink ? (
        <LinkInspector
          key={activeLink.linkId}
          entry={activeLink}
          onClose={() => handleClosePanel(activeLink.linkId)}
          onMinimize={() => handleMinimizePanel(activeLink.linkId)}
          onExplain={() => handleExplain(activeLink)}
          onTrack={handleTrack}
        />
      ) : expandedPanel ? (
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
          onThread={handleThreadChip}
        />
      ) : activeThreadStories && threadStoriesId ? (
        <ThreadStories
          key={threadStoriesId}
          title={activeThreadStories.title}
          total={activeThreadStories.total}
          articles={activeThreadStories.articles}
          loading={false}
          loadingMore={activeThreadStories.loadingMore}
          hasMore={activeThreadStories.hasMore}
          onLoadMore={handleMoreThreadStories}
          onClose={() => handleClosePanel(threadStoriesId)}
        />
      ) : (
        <>
          <p className="side-empty">
            {panelQueue.length + linkQueue.length > 0
              ? "Pick one above, or click a dot on the globe."
              : "Click a dot on the globe to see its stories here."}
          </p>
          {/* With Links on, its links: open one without pointing at its arc. */}
          {linksOn && (
            <LinkList links={links} rank={linkRank} status={linksNote} onOpen={handleLinkOpen} />
          )}
        </>
      )}
    </>
  );

  // From 1180px the open board takes the left of the screen: the other panels
  // hide and the globe slides right (soft-orbit.css .board-open).
  const split = boardOpen && wide;

  const content = (
    <main className={`relative h-screen w-screen overflow-hidden${split ? " board-open" : ""}`}>
      {/* Starfield, under everything */}
      <Sky />

      {/* Globe */}
      <Globe
        points={points}
        onPointClick={handleDotClick}
        onPointHover={hover.onPointHover}
        onEmptyClick={hover.onEmptyTap}
        onZoomChange={handleZoomChange}
        onReady={(controls) => {
          globeControlsRef.current = controls;
        }}
        reduced={reduced}
        lowPower={lowPower}
        touch={touch}
        layer={globeLayer}
        holdHeatmap={replaying || loading}
        replaying={replaying}
        links={links}
        alerts={breaking}
        inspectedLink={inspectedLink}
        onArcHover={setHoveredLink}
        onArcClick={handleLinkOpen}
        thread={globeThread}
        threadLit={spreadReplay.lit}
        onGrab={handleGrab}
        focus={globeFocus}
        board={boardMirror}
        shifted={split}
      />

      {/* Orbital rings around the globe */}
      <OrbitRings getGeometry={getGlobeGeometry} reduced={reduced} lowPower={lowPower} />

      {/* The hover card's reticle and leader, over the globe and under the chrome */}
      <GlobeHud
        point={cardPoint}
        project={projectPoint}
        getGeometry={getGlobeGeometry}
        cardRef={hoverCardRef}
        docked={touch}
        reduced={reduced}
      />

      {/* The hovered arc's pill, over the globe and under the chrome */}
      <ArcPill label={pillLink && linkPill(pillLink)} project={projectPoint} touch={touch} />

      {/* Top bar: brand, topics, status and About in one grid */}
      <TopBar
        activeTopic={activeTopic}
        onTopicChange={setActiveTopic}
        isLive={!apiError && !loading && timeWindow.kind === "live"}
        isLoading={loading}
        isOffline={apiError}
        isReplay={replaying}
        topicsRef={topicsRef}
        search={<TrackSearch variant="bar" inputRef={barSearchRef} {...searchHandlers("bar")} />}
        onSearchOpen={handleSearchOpen}
        searchOpen={!wide && sheetSearch}
        searchButtonRef={searchButtonRef}
        boardCount={board.pins.length}
        boardOpen={boardShown}
        onBoard={toggleBoard}
        boardButtonRef={boardButtonRef}
      />
      {/* The left column from 1180px: since your last visit, then the threads rail */}
      <div className={linksOn ? "left-stack links-on" : "left-stack"}>
        {since("strip")}
        {wide && threadsOn && (
          <ThreadsRail
            variant="rail"
            threads={threadsResult.threads}
            status={threadsNote}
            loading={threadsResult.loading}
            selected={selectedThread}
            detail={threadDetail}
            lit={spreadReplay.lit}
            onSelect={handleThreadSelect}
            onShowStories={handleShowThreadStories}
            onTrack={handleTrackName}
          />
        )}
      </div>

      {/* Co-pilot and stories, right (a bottom sheet below 1180px) */}
      <SidePanel
        tab={sideTab}
        onTabChange={handleSideTab}
        open={side.open}
        onOpenChange={side.setOpen}
        inspectCount={panelQueue.length + linkQueue.length + (tracked ? 1 : 0)}
        inspectRef={inspectRef}
        copilotRef={copilotRef}
        threadsRef={threadsTabRef}
        board={!wide && boardOpen ? boardView("sheet") : undefined}
        search={
          !wide && sheetSearch ? (
            <div ref={sheetSearchRef}>
              <TrackSearch
                variant="sheet"
                autoFocus
                inputRef={sheetInputRef}
                onDismiss={closeSheetSearch}
                {...searchHandlers("sheet")}
              />
            </div>
          ) : undefined
        }
        copilot={
          <CoPilot
            messages={agentMessages}
            isLoading={agentLoading}
            isDisabled={agentDisabled}
            activeTools={activeTools}
            context={{
              place: expandedPanel?.point.locationName,
              topic: activeTopic,
              window: timeWindow,
            }}
            onAsk={agentAsk}
            onStop={agentStop}
            onClear={agentClear}
            onCitationClick={handleCitationClick}
            onFlyTo={handleGlobeAction}
            showStoriesFor={showStoriesFor}
            showLinksFor={showLinksFor}
            breaking={breaking.length}
            callout={since("callout")}
          />
        }
        inspect={inspectTab}
        threads={
          wide ? undefined : (
            <ThreadsRail
              variant="sheet"
              threads={threadsResult.threads}
              status={threadsNote}
              loading={threadsResult.loading}
              selected={selectedThread}
              detail={threadDetail}
              lit={spreadReplay.lit}
              onSelect={handleThreadSelect}
              onShowStories={handleShowThreadStories}
              onTrack={handleTrackName}
            />
          )
        }
      />

      {/* The investigation board's split view, from 1180px (below, its list is in the sheet) */}
      {split && boardView("split")}

      {/* Bottom row: layers and the timeline, centred on the page. After the side
          panel: below 1180px the CSS lifts it above the sheet by sibling selectors. */}
      <BottomBar>
        <LayerSwitcher
          layer={globeLayer}
          onChange={setLayer}
          unavailable={lowPower ? { intensity: "Intensity is off in low-power mode" } : undefined}
          links={linksOn}
          onLinksChange={setLinksOn}
          rank={linkRank}
          onRankChange={setLinkRank}
          linksStatus={linksNote}
          threads={threadsOn}
          onThreadsChange={handleThreadsChange}
        />
        {/* Where the layers are hidden (phones), Links has a chip of its own. */}
        {linksOn && (
          <LinksChip
            status={linksNote}
            onOff={() => {
              setLinksOn(false);
              playRef.current?.focus(); // the chip goes: the focus moves on, not to the page
            }}
          />
        )}
        <TimelineCapsule
          timeWindow={timeWindow}
          onChange={changeWindow}
          onChoose={handleWindowChosen}
          onReplayChange={setReplaying}
          stories={points.reduce((sum, p) => sum + p.count, 0)}
          places={points.length}
          reduced={reduced}
          playRef={playRef}
          lastVisit={lastVisit}
          spread={
            selectedThread
              ? {
                  title: threadDetail?.title ?? selectedThread.title,
                  playing: spreadReplay.playing,
                  onPlay: spreadReplay.start,
                  onStop: spreadReplay.stop,
                }
              : null
          }
        />
        <BreakingTicker stories={breaking} reduced={reduced} onOpen={handleBreakingOpen} />
      </BottomBar>

      {/* For screen readers, always present so each new message is read: the hover
          card's label, and the Links status. Each in its own node, read when it changes. */}
      <p className="sr-only" aria-live="polite" data-testid="hover-announcer">
        <span>{cardPoint ? cardLabel(cardPoint) : ""}</span>
        <span>{linksNote ?? ""}</span>
        <span>{replayAnnouncement(globeThread?.spread ?? [], spreadReplay.phase)}</span>
        <span>{searchNote}</span>
        <span>{trackNote}</span>
        <span>{boardNote}</span>
      </p>

      {/* A share link's pins, for a board with pins of its own: asked, never merged by itself */}
      {sharedBoard.offer && (
        <BoardMergePrompt
          {...sharedBoard.offer}
          onAdd={sharedBoard.accept}
          onKeep={() => {
            sharedBoard.decline();
            boardButtonRef.current?.focus();
          }}
        />
      )}

      {/* City hover card: GlobeHud places it beside its dot (docked on touch screens) */}
      {shownCard && cardPoint && (
        <HoverCard
          key={cellKey(cardPoint.lat, cardPoint.lng)}
          ref={hoverCardRef}
          point={cardPoint}
          timeWindow={timeWindow}
          now={shownCard.shownAt}
          preview={previewIsCards ? preview : null}
          previewLoading={previewIsCards && previewLoading}
          revealed={revealed}
          onReveal={revealImage}
          docked={touch}
          linkedCountries={linksOn ? linkedCountries(links, cardPoint.countryCode) : null}
          onOpen={() => {
            dismissCard();
            handlePointClick(cardPoint);
          }}
          onTrack={handleTrack}
          onPointerEnter={hover.onCardEnter}
          onPointerLeave={hover.onCardLeave}
        />
      )}
    </main>
  );

  // Pin buttons in any panel reach the board through this.
  return <PinContext.Provider value={pinControls}>{content}</PinContext.Provider>;
}
