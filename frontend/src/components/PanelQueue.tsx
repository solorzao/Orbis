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
            onFiltersChange={(filters, filterSummary) =>
              onFiltersChange(expandedPanel.panelId, filters, filterSummary)
            }
          />
        )}
      </AnimatePresence>

      {/* Minimized tab stack -- desktop: right edge, mobile: bottom row */}
      {minimizedPanels.length > 0 && (
        <>
          {/* Wide: vertical stack on right, under the one-row top bar */}
          <div className="fixed top-16 right-3 z-40 hidden flex-col gap-2 min-[761px]:flex">
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

          {/* Up to 760px the top bar has two rows: stack under the topics */}
          <div className="fixed top-28 right-3 z-40 flex flex-col gap-2 sm:top-32 min-[761px]:hidden">
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
