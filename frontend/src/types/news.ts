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
  topic: Topic;
}

export interface PanelFilters {
  topics: string[];
  sentiment: string | null;
  search: string;
}

export interface PanelEntry {
  panelId: string;
  point: GlobePoint;
  articles: NewsArticle[];
  clusterSummary: string | null;
  articlesLoading: boolean;
  summaryLoading: boolean;
  createdAt: number;
  loadingMore?: boolean;
}
