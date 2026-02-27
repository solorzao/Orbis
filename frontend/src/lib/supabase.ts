/**
 * Supabase client and TypeScript types for the Orbis frontend.
 *
 * Install the dependency before importing:
 *   npm install @supabase/supabase-js
 */

import { createClient, SupabaseClient } from "@supabase/supabase-js";

// ---------------------------------------------------------------------------
// Environment variables (set in .env.local for Next.js)
// ---------------------------------------------------------------------------

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

// ---------------------------------------------------------------------------
// Supabase client singleton
// ---------------------------------------------------------------------------

export const supabase: SupabaseClient<Database> = createClient<Database>(
  supabaseUrl,
  supabaseAnonKey,
);

// ---------------------------------------------------------------------------
// Database schema types
// ---------------------------------------------------------------------------

/** A single article row as stored in the `articles` table. */
export interface Article {
  id: string;
  title: string;
  summary: string | null;
  source_url: string;
  source_name: string;
  source_language: string;
  published_at: string; // ISO-8601 timestamptz
  ingested_at: string;
  // `location` is a PostGIS geography — typically not returned directly
  latitude: number;
  longitude: number;
  country_code: string | null;
  region: string | null;
  topic_tags: string[];
  sentiment_score: number;
  entities: Record<string, unknown>;
  embedding: number[] | null;
  image_url: string | null;
}

/** Shape returned by the `cluster_articles` RPC function. */
export interface ArticleCluster {
  cluster_lat: number;
  cluster_lng: number;
  article_count: number;
}

/** Shape returned by the `topic_counts` RPC function. */
export interface TopicCount {
  topic: string;
  count: number;
}

// ---------------------------------------------------------------------------
// Supabase generated-style Database type (subset)
// ---------------------------------------------------------------------------

export interface Database {
  public: {
    Tables: {
      articles: {
        Row: Article;
        Insert: Omit<Article, "id" | "ingested_at"> & {
          id?: string;
          ingested_at?: string;
        };
        Update: Partial<Article>;
      };
    };
    Functions: {
      nearby_articles: {
        Args: {
          lat: number;
          lng: number;
          radius_km?: number;
          limit_count?: number;
        };
        Returns: Article[];
      };
      articles_in_bounds: {
        Args: {
          min_lat: number;
          min_lng: number;
          max_lat: number;
          max_lng: number;
          limit_count?: number;
        };
        Returns: Article[];
      };
      cluster_articles: {
        Args: {
          cell_size?: number;
        };
        Returns: ArticleCluster[];
      };
      topic_counts: {
        Args: Record<string, never>;
        Returns: TopicCount[];
      };
    };
    Views: Record<string, never>;
    Enums: Record<string, never>;
  };
}
