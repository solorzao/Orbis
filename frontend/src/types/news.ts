export interface NewsArticle {
  id: string;
  title: string;
  summary?: string;
  sourceUrl: string;
  sourceName: string;
  publishedAt: string;
  latitude: number;
  longitude: number;
  countryCode: string;
  topicTags: string[];
  sentimentScore: number; // -1 to 1, negative = bad, positive = good
}

export type Topic =
  | "All"
  | "Politics"
  | "Conflict"
  | "Technology"
  | "Climate"
  | "Economy"
  | "Health";

export interface GlobePoint {
  id: string;
  lat: number;
  lng: number;
  size: number;
  color: string;
  articles: NewsArticle[];
  isCluster: boolean;
  count: number;
  locationName?: string;
  /** Sets the colour: the newest story's topic. */
  topic: Topic;
  /** Every topic in the cell, for the topic filter. */
  topics?: Topic[];
}

export interface PanelFilters {
  topics: string[];
  sentiment: string | null;
  search: string;
}

/** What a panel lists and summarises, fixed when its dot is clicked. */
export interface PanelQuery {
  topic?: Topic;
  startTime: string;
  endTime: string;
  /** Opened without a selected window: the last 24 hours up to the click. */
  live: boolean;
}

export interface PanelEntry {
  panelId: string;
  point: GlobePoint;
  query: PanelQuery;
  articles: NewsArticle[];
  /** Offset of the next page: rows received so far, duplicates included. */
  nextOffset: number;
  clusterSummary: string | null;
  articlesLoading: boolean;
  summaryLoading: boolean;
  createdAt: number;
  loadingMore?: boolean;
  filters?: PanelFilters;
  filterSummary?: string | null;
}
