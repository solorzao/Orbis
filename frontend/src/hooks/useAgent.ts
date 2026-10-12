"use client";

import { useState, useRef, useCallback } from "react";
import type { Topic } from "@/types/news";

export interface Citation {
  title: string;
  url: string;
  source_name: string;
  lat: number;
  lng: number;
}

/** A place the answer names; the backend sends only fly-tos (agent._normalize_globe_actions). */
export interface GlobeAction {
  type: "flyTo";
  lat: number;
  lng: number;
  /** The place's name, cleaned on receipt (cleanLabel); may be empty. */
  label?: string;
}

/**
 * What the visitor sees, sent with a question to scope the co-pilot (backend
 * AskRequest.context). Each field is optional; the window's bounds are ISO
 * times taken when the question is asked.
 */
export interface AskContext {
  place?: string;
  topic?: Exclude<Topic, "All">;
  startTime?: string;
  endTime?: string;
}

const MAX_LABEL = 80;
const MAX_TITLE = 300;
const MAX_ACTIONS = 3;

// C0 and C1 controls, zero-width and bidi marks, word joiners, isolates and the BOM
const INVISIBLE = /[\u0000-\u001f\u007f-\u009f\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]/g;

/**
 * Model- or source-controlled text made safe to show as one line: control,
 * bidi and zero-width characters go (they could reorder or hide what a pill
 * says), whitespace collapses, and it is capped at `max` characters.
 */
export function cleanLabel(s: unknown, max = MAX_LABEL): string {
  if (typeof s !== "string") return "";
  return s
    .replace(/\s/g, " ")
    .replace(INVISIBLE, "")
    .replace(/ +/g, " ")
    .trim()
    .slice(0, max)
    .trimEnd();
}

function isCoordinate(v: unknown, limit: number): v is number {
  return typeof v === "number" && Number.isFinite(v) && Math.abs(v) <= limit;
}

/** The done event's actions: well-formed fly-tos only, at most three, labels cleaned. */
function readGlobeActions(raw: unknown): GlobeAction[] {
  if (!Array.isArray(raw)) return [];
  const actions: GlobeAction[] = [];
  for (const a of raw) {
    if (!a || a.type !== "flyTo" || !isCoordinate(a.lat, 90) || !isCoordinate(a.lng, 180)) continue;
    actions.push({ type: "flyTo", lat: a.lat, lng: a.lng, label: cleanLabel(a.label) });
    if (actions.length === MAX_ACTIONS) break;
  }
  return actions;
}

/** The done event's citations, with their titles and sources cleaned for display. */
function readCitations(raw: unknown): Citation[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((c) => c && typeof c === "object")
    .map((c) => ({
      title: cleanLabel(c.title, MAX_TITLE),
      url: typeof c.url === "string" ? c.url : "",
      source_name: cleanLabel(c.source_name),
      lat: typeof c.lat === "number" ? c.lat : 0,
      lng: typeof c.lng === "number" ? c.lng : 0,
    }));
}

/** The request's context in the backend's field names, or undefined when it has none. */
function contextBody(context?: AskContext) {
  if (!context) return undefined;
  const body = {
    place: context.place || undefined,
    topic: context.topic || undefined,
    start_time: context.startTime || undefined,
    end_time: context.endTime || undefined,
  };
  return Object.values(body).some(Boolean) ? body : undefined;
}

export interface AgentMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  globeActions?: GlobeAction[];
  toolsUsed?: string[];
  status?: "streaming" | "complete" | "error";
}

interface UseAgentOptions {
  onGlobeAction?: (action: GlobeAction) => void;
}

export function useAgent({ onGlobeAction }: UseAgentOptions = {}) {
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isDisabled, setIsDisabled] = useState(false);
  const [activeTools, setActiveTools] = useState<string[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const conversationIdRef = useRef(crypto.randomUUID());
  const onGlobeActionRef = useRef(onGlobeAction);
  onGlobeActionRef.current = onGlobeAction;

  const ask = useCallback(
    async (question: string, context?: AskContext) => {
      if (!question.trim() || isLoading) return;

      const userMsg: AgentMessage = {
        id: crypto.randomUUID(),
        role: "user",
        content: question.trim(),
      };

      const assistantId = crypto.randomUUID();
      const assistantMsg: AgentMessage = {
        id: assistantId,
        role: "assistant",
        content: "",
        status: "streaming",
      };

      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setIsLoading(true);
      setActiveTools([]);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        // Proxied to the backend by src/app/api/[...path]/route.ts
        const res = await fetch("/api/agent/ask/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question: question.trim(),
            conversation_id: conversationIdRef.current,
            context: contextBody(context),
          }),
          signal: controller.signal,
        });

        if (res.status === 503) {
          setIsDisabled(true);
          throw new Error("Agent is temporarily disabled.");
        }

        if (!res.ok || !res.body) {
          throw new Error(`HTTP ${res.status}`);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let currentEvent = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          // Keep the last partial line in the buffer
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (line.startsWith("event: ")) {
              currentEvent = line.slice(7).trim();
            } else if (line.startsWith("data: ")) {
              const dataStr = line.slice(6);
              try {
                const data = JSON.parse(dataStr);

                if (currentEvent === "planning") {
                  const tools: string[] = data.tools || [];
                  setActiveTools(tools);
                } else if (currentEvent === "token") {
                  const token: string = data.token || "";
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantId ? { ...m, content: m.content + token } : m,
                    ),
                  );
                } else if (currentEvent === "done") {
                  const citations = readCitations(data.citations);
                  const globeActions = readGlobeActions(data.globe_actions);
                  const toolsUsed: string[] = data.tools_used || [];

                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantId
                        ? {
                            ...m,
                            citations,
                            globeActions,
                            toolsUsed,
                            status: "complete",
                          }
                        : m,
                    ),
                  );

                  // Each flyTo starts a camera tween, so dispatching several at
                  // once would land on the last (least relevant) one.
                  const [primary] = globeActions;
                  if (primary) onGlobeActionRef.current?.(primary);

                  setActiveTools([]);
                }
              } catch {
                // Ignore malformed JSON lines
              }
            }
          }
        }

        // If we finished reading without a done event, mark complete
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId && m.status === "streaming" ? { ...m, status: "complete" } : m,
          ),
        );
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    content: m.content || "Something went wrong. Please try again.",
                    status: "error",
                  }
                : m,
            ),
          );
        }
      } finally {
        setIsLoading(false);
        setActiveTools([]);
        abortRef.current = null;
      }
    },
    [isLoading],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  const clear = useCallback(() => {
    setMessages([]);
    setActiveTools([]);
    conversationIdRef.current = crypto.randomUUID();
  }, []);

  return { messages, isLoading, isDisabled, activeTools, ask, stop, clear };
}
