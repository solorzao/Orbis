"use client";

import { AnimatePresence } from "framer-motion";
import { PanelEntry, PanelFilters } from "@/types/news";
import NewsPanel from "@/components/NewsPanel";
import PanelTab from "@/components/PanelTab";

interface PanelQueueProps {
  panelQueue: PanelEntry[];
  expandedPanelId: string | null;
  onExpandPanel: (panelId: string) => void;
  onClosePanel: (panelId: string) => void;
  onMinimizePanel: () => void;
  onLoadMore: (panelId: string, filters?: PanelFilters) => void;
  onFiltersChange: (panelId: string, filters: PanelFilters, filterSummary: string | null) => void;
}

export default function PanelQueue({
  panelQueue,
  expandedPanelId,
  onExpandPanel,
  onClosePanel,
  onMinimizePanel,
  onLoadMore,
  onFiltersChange,
}: PanelQueueProps) {
  const expandedPanel = panelQueue.find((p) => p.panelId === expandedPanelId) ?? null;
  const minimizedPanels = panelQueue.filter((p) => p.panelId !== expandedPanelId);

  return (
    <>
      {/* Expanded panel */}
      <AnimatePresence>
        {expandedPanel && (
          <NewsPanel
            key={expandedPanel.panelId}
            point={{ ...expandedPanel.point, articles: expandedPanel.articles }}
            onClose={() => onClosePanel(expandedPanel.panelId)}
            onMinimize={onMinimizePanel}
            onLoadMore={(filters) => onLoadMore(expandedPanel.panelId, filters)}
            loadingMore={expandedPanel.loadingMore}
            clusterSummary={expandedPanel.clusterSummary}
            summaryLoading={expandedPanel.summaryLoading}
            articlesLoading={expandedPanel.articlesLoading}
            savedFilters={expandedPanel.filters}
            savedFilterSummary={expandedPanel.filterSummary}
            onFiltersChange={(filters, filterSummary) => onFiltersChange(expandedPanel.panelId, filters, filterSummary)}
          />
        )}
      </AnimatePresence>

      {/* Minimized tab stack -- desktop: right edge, mobile: bottom row */}
      {minimizedPanels.length > 0 && (
        <>
          {/* Desktop: vertical stack on right */}
          <div className="fixed right-3 top-16 z-40 hidden flex-col gap-2 sm:flex">
            <AnimatePresence>
              {minimizedPanels.map((entry) => (
                <PanelTab
                  key={entry.panelId}
                  entry={entry}
                  onExpand={onExpandPanel}
                  onClose={onClosePanel}
                />
              ))}
            </AnimatePresence>
          </div>

          {/* Mobile: vertical stack on right, under category bar */}
          <div className="fixed right-3 top-16 z-40 flex flex-col gap-2 sm:hidden">
            <AnimatePresence>
              {minimizedPanels.map((entry) => (
                <PanelTab
                  key={entry.panelId}
                  entry={entry}
                  onExpand={onExpandPanel}
                  onClose={onClosePanel}
                />
              ))}
            </AnimatePresence>
          </div>
        </>
      )}
    </>
  );
}
