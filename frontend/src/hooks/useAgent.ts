"use client";

import { useState, useRef, useCallback } from "react";

export interface Citation {
  title: string;
  url: string;
  source_name: string;
  lat: number;
  lng: number;
}

export interface GlobeAction {
  type: "flyTo" | "highlight";
  lat: number;
  lng: number;
  zoom?: number;
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
  const [activeTools, setActiveTools] = useState<string[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const conversationIdRef = useRef(crypto.randomUUID());
  const onGlobeActionRef = useRef(onGlobeAction);
  onGlobeActionRef.current = onGlobeAction;

  const apiBase = process.env.NEXT_PUBLIC_API_URL || "";

  const ask = useCallback(
    async (question: string) => {
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
        const res = await fetch(`${apiBase}/api/agent/ask/stream`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question: question.trim(),
            conversation_id: conversationIdRef.current,
          }),
          signal: controller.signal,
        });

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
                      m.id === assistantId
                        ? { ...m, content: m.content + token }
                        : m,
                    ),
                  );
                } else if (currentEvent === "done") {
                  const citations: Citation[] = data.citations || [];
                  const globeActions: GlobeAction[] = data.globe_actions || [];
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

                  for (const action of globeActions) {
                    onGlobeActionRef.current?.(action);
                  }

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
            m.id === assistantId && m.status === "streaming"
              ? { ...m, status: "complete" }
              : m,
          ),
        );
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    content:
                      m.content || "Something went wrong. Please try again.",
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
    [isLoading, apiBase],
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

  return { messages, isLoading, activeTools, ask, stop, clear };
}
