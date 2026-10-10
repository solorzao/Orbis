import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useAgent } from "./useAgent";

const mockFetch = vi.fn();

beforeEach(() => {
  mockFetch.mockReset();
  vi.stubGlobal("fetch", mockFetch);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/** One SSE event, framed the way the backend's sse-starlette sends it (CRLF). */
function sseEvent(event: string, data: unknown): string {
  return `event: ${event}\r\ndata: ${JSON.stringify(data)}\r\n\r\n`;
}

function streamResponse(body: string) {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(body));
      controller.close();
    },
  });
  return { ok: true, status: 200, body: stream };
}

describe("useAgent", () => {
  it("flies the globe to the first action only", async () => {
    const lagos = { type: "flyTo", lat: 6.45, lng: 3.39, label: "Lagos" };
    const accra = { type: "flyTo", lat: 5.6, lng: -0.19, label: "Accra" };
    mockFetch.mockResolvedValue(
      streamResponse(
        sseEvent("done", { citations: [], globe_actions: [lagos, accra], tools_used: [] }),
      ),
    );
    const onGlobeAction = vi.fn();
    const { result } = renderHook(() => useAgent({ onGlobeAction }));

    await act(async () => {
      await result.current.ask("What is happening in West Africa?");
    });

    expect(onGlobeAction).toHaveBeenCalledTimes(1);
    expect(onGlobeAction).toHaveBeenCalledWith(lagos);
  });
});
