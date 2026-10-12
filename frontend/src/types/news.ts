import type { LiveHours } from "@/lib/timeWindow";

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

/** A place's lead story, for the hover card: its newest, preferring one with an image. */
export interface GlobeLead {
  title: string;
  sourceName: string;
  publishedAt: string;
  /** A public https image, or null. */
  imageUrl: string | null;
  /** The story's first topic; "All" when it is none of the six. */
  topic: Topic;
  /** Conflict is among its tags: its image is veiled until the visitor asks. */
  sensitive: boolean;
}

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
  /**
   * Sets the colour: the place's most common topic (so it holds still as
   * stories arrive), or the topic the globe is filtered to.
   */
  topic: Topic;
  /** ISO 3166-1 alpha-2 of the lead story's place. */
  countryCode?: string;
  lead?: GlobeLead;
  /** Stories per topic (a story with two topics counts for both). */
  topicMix?: Partial<Record<Topic, number>>;
  /** Mean sentiment of the place's stories, -1 to 1. */
  tone?: number;
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
  /** Opened on a live window: the last `hours` up to the click. */
  live: boolean;
  /** A live panel's preset (see timeWindow): live panels match on it. */
  hours?: LiveHours;
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
