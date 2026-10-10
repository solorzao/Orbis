import { describe, it, expect } from "vitest";
import {
  CLIENT_IP_HEADER,
  buildUpstreamUrl,
  downstreamResponseHeaders,
  upstreamRequestHeaders,
  visitorIp,
} from "./backendProxy";

describe("buildUpstreamUrl", () => {
  it("maps catch-all segments onto the backend /api path with the query", () => {
    expect(buildUpstreamUrl("https://api.example/", ["news", "cluster"], "?lat=1&lng=2")).toBe(
      "https://api.example/api/news/cluster?lat=1&lng=2",
    );
  });

  it("rejects dot segments that would escape the /api prefix", () => {
    expect(buildUpstreamUrl("https://api.example", ["..", "docs"], "")).toBeNull();
    expect(buildUpstreamUrl("https://api.example", ["news", "."], "")).toBeNull();
  });

  it("encodes slashes inside a segment", () => {
    expect(buildUpstreamUrl("https://api.example", ["a/b"], "")).toBe(
      "https://api.example/api/a%2Fb",
    );
  });
});

describe("visitorIp", () => {
  it("prefers x-real-ip", () => {
    expect(
      visitorIp(new Headers({ "x-real-ip": "203.0.113.7", "x-forwarded-for": "1.1.1.1" })),
    ).toBe("203.0.113.7");
  });

  it("falls back to the first x-forwarded-for entry", () => {
    expect(visitorIp(new Headers({ "x-forwarded-for": "203.0.113.7, 10.0.0.1" }))).toBe(
      "203.0.113.7",
    );
  });

  it("returns null when unknown", () => {
    expect(visitorIp(new Headers())).toBeNull();
  });
});

describe("upstreamRequestHeaders", () => {
  it("adds the API key and visitor IP, and drops unrelated headers", () => {
    const incoming = new Headers({
      "content-type": "application/json",
      cookie: "session=secret",
      "x-real-ip": "203.0.113.7",
      "X-API-Key": "client-supplied",
    });
    const out = upstreamRequestHeaders(incoming, "server-key");
    expect(out.get("X-API-Key")).toBe("server-key");
    expect(out.get(CLIENT_IP_HEADER)).toBe("203.0.113.7");
    expect(out.get("content-type")).toBe("application/json");
    expect(out.has("cookie")).toBe(false);
  });

  it("omits the key header when none is configured", () => {
    expect(upstreamRequestHeaders(new Headers(), "").has("X-API-Key")).toBe(false);
  });
});

describe("downstreamResponseHeaders", () => {
  it("passes through content-type and retry-after only", () => {
    const out = downstreamResponseHeaders(
      new Headers({ "content-type": "application/json", "retry-after": "60", server: "uvicorn" }),
    );
    expect(out.get("content-type")).toBe("application/json");
    expect(out.get("retry-after")).toBe("60");
    expect(out.has("server")).toBe(false);
  });

  it("disables buffering for event streams", () => {
    const out = downstreamResponseHeaders(new Headers({ "content-type": "text/event-stream" }));
    expect(out.get("cache-control")).toBe("no-cache, no-transform");
    expect(out.get("x-accel-buffering")).toBe("no");
  });
});
