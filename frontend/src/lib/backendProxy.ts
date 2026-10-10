/**
 * Server-side helpers for proxying browser requests to the Orbis API.
 *
 * The browser calls same-origin /api/* routes; the Next.js route handler
 * forwards them to the backend and attaches the API key, which therefore
 * never ships in the client bundle.
 */

export const CLIENT_IP_HEADER = "X-Orbis-Client-IP";

/** Response headers worth passing back to the browser. */
const PASSTHROUGH_RESPONSE_HEADERS = ["content-type", "cache-control", "retry-after"];

/**
 * Backend URL for a catch-all route's segments, or null if a segment would
 * step outside /api (encodeURIComponent leaves "." and ".." unchanged).
 */
export function buildUpstreamUrl(base: string, segments: string[], search: string): string | null {
  if (segments.some((s) => s === "." || s === "..")) return null;
  const path = segments.map(encodeURIComponent).join("/");
  return `${base.replace(/\/+$/, "")}/api/${path}${search}`;
}

/**
 * The visitor's IP as reported by Vercel's edge, which overwrites any
 * client-supplied value in these headers.
 */
export function visitorIp(headers: Headers): string | null {
  const realIp = headers.get("x-real-ip");
  if (realIp) return realIp.trim();
  const forwarded = headers.get("x-forwarded-for");
  return forwarded ? forwarded.split(",")[0].trim() : null;
}

export function upstreamRequestHeaders(incoming: Headers, apiKey: string): Headers {
  const headers = new Headers();
  for (const name of ["content-type", "accept"]) {
    const value = incoming.get(name);
    if (value) headers.set(name, value);
  }
  if (apiKey) headers.set("X-API-Key", apiKey);
  const ip = visitorIp(incoming);
  if (ip) headers.set(CLIENT_IP_HEADER, ip);
  return headers;
}

export function downstreamResponseHeaders(upstream: Headers): Headers {
  const headers = new Headers();
  for (const name of PASSTHROUGH_RESPONSE_HEADERS) {
    const value = upstream.get(name);
    if (value) headers.set(name, value);
  }
  if (headers.get("content-type")?.startsWith("text/event-stream")) {
    // Keep agent answers streaming instead of buffering at the edge.
    headers.set("cache-control", "no-cache, no-transform");
    headers.set("x-accel-buffering", "no");
  }
  return headers;
}
