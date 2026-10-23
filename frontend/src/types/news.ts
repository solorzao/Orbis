import type { LiveHours } from "@/lib/timeWindow";
import type { Relation, RelationDetail, RelationKind, RelationLens } from "@/lib/relations";

/** The story thread a cluster story is part of (/api/news/cluster), when it would be listed. */
export interface ArticleThread {
  id: number;
  /** The thread's AI title, else its lead story's headline. */
  title: string;
  /** Its first three place names. */
  places: string[];
}

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
  /** Where the story is placed, e.g. "Paris, France" ("" when unknown). */
  region?: string;
  topicTags: string[];
  sentimentScore: number; // -1 to 1, negative = bad, positive = good
  /** The developing story it is part of (a place's stories only), or null. */
  thread?: ArticleThread | null;
}

export type Topic =
  "All" | "Politics" | "Conflict" | "Technology" | "Climate" | "Economy" | "Health";

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

/** One end of a co-coverage link: a country and its label point. */
export interface LinkCountry {
  /** ISO 3166-1 alpha-2. */
  iso: string;
  name: string;
  lat: number;
  lng: number;
}

/**
 * Two countries the window's stories cover together (/api/links): an arc on
 * the globe. `a` and `b` come in code order; `from` is the end most of the
 * stories come from, where the arc starts.
 */
export interface CountryLink {
  a: LinkCountry;
  b: LinkCountry;
  /** Stories that link the two. */
  n: number;
  /** How many times more often than chance they are covered together. */
  lift: number;
  /** The stories' main topic pill ("All" when it is none of the six). */
  topic: Topic;
  /** Mean sentiment of the stories, -1 to 1. */
  tone: number;
  /** ISO code of the end most of the stories come from. */
  from: string;
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

/** What the link inspector shows for a pair (/api/links/detail), the pair in code order. */
export interface LinkDetail {
  a: LinkCountry;
  b: LinkCountry;
  n: number;
  lift: number;
  /** Stories per topic pill (a story with two topics counts for both). */
  topicMix: Partial<Record<Topic, number>>;
  tone: number;
  /** People and organisations named in two or more of the stories. */
  shared: { name: string; type: "person" | "org"; n: number }[];
  /** The stories' top themes, as words. */
  themes: string[];
  /** The newest distinct stories that link the two. */
  articles: NewsArticle[];
}

/** A link's explanation: Claude's words (ai), or a message saying why there are none. */
export interface LinkExplanation {
  text: string;
  ai: boolean;
}

/**
 * A relation open in the Inspect tab (like a LinkEntry, without an
 * explanation). No query: every relation covers the same fixed 7-day lens,
 * so the pair alone names it.
 */
export interface RelationEntry {
  relationId: string;
  /** The relation as its arc or list row had it: its ends, numbers and acting country. */
  relation: Relation;
  /** The class switch it was opened under: other than "all", `relation`'s numbers are that class's alone. */
  filter: RelationKind;
  /** The lens the list answered for, until the detail names its own; null if unknown. */
  lens: RelationLens | null;
  detail: RelationDetail | null;
  detailLoading: boolean;
  detailError?: boolean;
  /** The pair has no events left in the lens (a 404 around UTC midnight): said as text. */
  notFound?: boolean;
  createdAt: number;
}

/** A link open in the Inspect tab, its query fixed when it was opened (like a panel's). */
export interface LinkEntry {
  linkId: string;
  /** The link as its arc had it: its ends, numbers and origin. */
  link: CountryLink;
  query: PanelQuery;
  detail: LinkDetail | null;
  detailLoading: boolean;
  detailError?: boolean;
  /** When the detail landed (Date.now()), for its stories' ages. */
  loadedAt?: number;
  explanation: LinkExplanation | null;
  explaining: boolean;
  createdAt: number;
}
