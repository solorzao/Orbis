import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { cleanLabel, isWebUrl, useAgent } from "./useAgent";

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

function doneResponse(done: Record<string, unknown>) {
  return streamResponse(
    sseEvent("done", { citations: [], globe_actions: [], tools_used: [], ...done }),
  );
}

/** Characters that change how text displays without showing themselves. */
const ch = (code: number) => String.fromCharCode(code);
const RLO = ch(0x202e); // right-to-left override
const LRI = ch(0x2066); // left-to-right isolate
const PDI = ch(0x2069); // pop directional isolate
const ZWSP = ch(0x200b); // zero-width space
const RLM = ch(0x200f); // right-to-left mark
const NEL = ch(0x85); // C1 next line
const BOM = ch(0xfeff);

describe("cleanLabel", () => {
  it("strips control and bidi characters", () => {
    expect(cleanLabel(`La${ZWSP}gos${RLO}`)).toBe("Lagos");
    expect(cleanLabel(`${LRI}Accra${PDI}${RLM}`)).toBe("Accra");
    expect(cleanLabel(`Kyiv\u0000\u0007\u001b[31m${NEL}${BOM}`)).toBe("Kyiv[31m");
  });

  it("collapses whitespace to one line", () => {
    expect(cleanLabel("  Lagos,\n\t Nigeria \r\n")).toBe("Lagos, Nigeria");
    expect(cleanLabel(`Lagos ${ZWSP} Nigeria`)).toBe("Lagos Nigeria");
  });

  it("caps labels at 80 characters", () => {
    const label = cleanLabel("Lagos " + "x".repeat(200));
    expect(label).toHaveLength(80);
    expect(label.startsWith("Lagos xxx")).toBe(true);
    expect(cleanLabel("a".repeat(79) + " b")).toBe("a".repeat(79)); // no trailing space
  });

  it("is empty for a missing label", () => {
    expect(cleanLabel(undefined)).toBe("");
    expect(cleanLabel(42)).toBe("");
  });
});

describe("isWebUrl", () => {
  it("is true for http(s) links only", () => {
    expect(isWebUrl("https://example.com")).toBe(true);
    expect(isWebUrl("http://example.com")).toBe(true);
    expect(isWebUrl("javascript:alert(1)")).toBe(false);
    expect(isWebUrl("")).toBe(false);
    expect(isWebUrl(undefined)).toBe(false);
  });
});

describe("useAgent", () => {
  it("flies the globe to the first action only", async () => {
    const lagos = { type: "flyTo", lat: 6.45, lng: 3.39, label: "Lagos" };
    const accra = { type: "flyTo", lat: 5.6, lng: -0.19, label: "Accra" };
    mockFetch.mockResolvedValue(doneResponse({ globe_actions: [lagos, accra] }));
    const onGlobeAction = vi.fn();
    const { result } = renderHook(() => useAgent({ onGlobeAction }));

    await act(async () => {
      await result.current.ask("What is happening in West Africa?");
    });

    expect(onGlobeAction).toHaveBeenCalledTimes(1);
    expect(onGlobeAction).toHaveBeenCalledWith(lagos);
  });

  it("cleans every action label on receipt", async () => {
    mockFetch.mockResolvedValue(
      doneResponse({
        globe_actions: [
          { type: "flyTo", lat: 6.45, lng: 3.39, label: `${RLO}Lagos,\n Nigeria` },
          { type: "flyTo", lat: 5.6, lng: -0.19, label: "y".repeat(120) },
          { type: "flyTo", lat: 9.06, lng: 7.49 },
        ],
      }),
    );
    const onGlobeAction = vi.fn();
    const { result } = renderHook(() => useAgent({ onGlobeAction }));

    await act(async () => {
      await result.current.ask("West Africa?");
    });

    const actions = result.current.messages[1].globeActions!;
    expect(actions.map((a) => a.label)).toEqual(["Lagos, Nigeria", "y".repeat(80), ""]);
    expect(onGlobeAction).toHaveBeenCalledWith(
      expect.objectContaining({ label: "Lagos, Nigeria" }),
    );
  });

  it("keeps only well-formed fly-to actions, at most three", async () => {
    mockFetch.mockResolvedValue(
      doneResponse({
        globe_actions: [
          { type: "highlight", lat: 1, lng: 1, label: "Old" },
          { type: "flyTo", lat: "1", lng: 1 },
          { type: "flyTo", lat: 1, lng: 1, label: "A" },
          { type: "flyTo", lat: 2, lng: 2, label: "B" },
          { type: "flyTo", lat: 3, lng: 3, label: "C" },
          { type: "flyTo", lat: 4, lng: 4, label: "D" },
        ],
      }),
    );
    const { result } = renderHook(() => useAgent());

    await act(async () => {
      await result.current.ask("Where?");
    });

    expect(result.current.messages[1].globeActions!.map((a) => a.label)).toEqual(["A", "B", "C"]);
  });

  it("cleans citation titles and sources on receipt", async () => {
    mockFetch.mockResolvedValue(
      doneResponse({
        citations: [
          {
            title: `Floods ${RLO}in\nLagos`,
            url: "https://example.com/a",
            source_name: `${LRI}Reuters${PDI}`,
            lat: 6.45,
            lng: 3.39,
          },
        ],
      }),
    );
    const { result } = renderHook(() => useAgent());

    await act(async () => {
      await result.current.ask("Lagos?");
    });

    const [citation] = result.current.messages[1].citations!;
    expect(citation.index).toBeUndefined();
    expect(citation.title).toBe("Floods in Lagos");
    expect(citation.source_name).toBe("Reuters");
    expect(citation.url).toBe("https://example.com/a");
  });

  it("keeps only http(s) citation links", async () => {
    const cite = { title: "T", source_name: "Wire", lat: 0, lng: 0 };
    const urls = [
      "https://example.com/a",
      "HTTP://example.com/b",
      "javascript:alert(1)",
      " javascript:alert(1)",
      "data:text/html,hi",
      "//evil.com",
      42,
    ];
    mockFetch.mockResolvedValue(doneResponse({ citations: urls.map((url) => ({ ...cite, url })) }));
    const { result } = renderHook(() => useAgent());

    await act(async () => {
      await result.current.ask("Lagos?");
    });

    expect(result.current.messages[1].citations!.map((c) => c.url)).toEqual([
      "https://example.com/a",
      "HTTP://example.com/b",
      "",
      "",
      "",
      "",
      "",
    ]);
  });

  it("keeps the number each citation is cited by", async () => {
    const cite = { url: "https://e.com", source_name: "Wire", lat: 0, lng: 0 };
    mockFetch.mockResolvedValue(
      doneResponse({
        citations: [
          { ...cite, index: 4, title: "Four" },
          { ...cite, index: null, title: "None" },
          { ...cite, index: "2", title: "Text" },
        ],
      }),
    );
    const { result } = renderHook(() => useAgent());

    await act(async () => {
      await result.current.ask("Lagos?");
    });

    expect(result.current.messages[1].citations!.map((c) => c.index)).toEqual([
      4,
      undefined,
      undefined,
    ]);
  });

  it("sends the screen context in the request body", async () => {
    mockFetch.mockResolvedValue(doneResponse({}));
    const { result } = renderHook(() => useAgent());

    await act(async () => {
      await result.current.ask("  Brief me on Madrid, Spain  ", {
        place: "Madrid, Spain",
        topic: "Politics",
        startTime: "2026-10-11T02:00:00.000Z",
        endTime: "2026-10-11T14:00:00.000Z",
      });
    });

    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body).toEqual({
      question: "Brief me on Madrid, Spain",
      conversation_id: expect.any(String),
      context: {
        place: "Madrid, Spain",
        topic: "Politics",
        start_time: "2026-10-11T02:00:00.000Z",
        end_time: "2026-10-11T14:00:00.000Z",
      },
    });
  });

  it("sends only the context fields given", async () => {
    mockFetch.mockResolvedValue(doneResponse({}));
    const { result } = renderHook(() => useAgent());

    await act(async () => {
      await result.current.ask("Any news?", { topic: "Health" });
    });

    expect(JSON.parse(mockFetch.mock.calls[0][1].body).context).toEqual({ topic: "Health" });
  });

  it("without context sends the same body as before", async () => {
    mockFetch.mockResolvedValue(doneResponse({}));
    const { result } = renderHook(() => useAgent());

    await act(async () => {
      await result.current.ask("What is happening?");
    });
    mockFetch.mockResolvedValue(doneResponse({}));
    await act(async () => {
      await result.current.ask("And now?", {});
    });

    for (const [, init] of mockFetch.mock.calls) {
      expect(Object.keys(JSON.parse(init.body))).toEqual(["question", "conversation_id"]);
    }
  });
});
