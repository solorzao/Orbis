import type { NextRequest } from "next/server";
import {
  buildUpstreamUrl,
  downstreamResponseHeaders,
  upstreamRequestHeaders,
} from "@/lib/backendProxy";

// Proxies /api/* to the Orbis backend, adding the API key server-side.
export const dynamic = "force-dynamic";
// Agent answers and AI summaries can take a while on cold paths.
export const maxDuration = 120;

const API_URL = process.env.ORBIS_API_URL || "http://localhost:8000";
const API_KEY = process.env.ORBIS_API_KEY || "";

type RouteContext = { params: Promise<{ path: string[] }> };

async function proxy(req: NextRequest, { params }: RouteContext): Promise<Response> {
  const { path } = await params;
  const url = buildUpstreamUrl(API_URL, path, req.nextUrl.search);
  if (!url) return Response.json({ detail: "Invalid path." }, { status: 400 });
  const hasBody = req.method !== "GET" && req.method !== "HEAD";

  let upstream: Response;
  try {
    upstream = await fetch(url, {
      method: req.method,
      headers: upstreamRequestHeaders(req.headers, API_KEY),
      body: hasBody ? await req.arrayBuffer() : undefined,
      signal: req.signal,
      cache: "no-store",
    });
  } catch {
    return Response.json({ detail: "Upstream API unavailable." }, { status: 502 });
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: downstreamResponseHeaders(upstream.headers),
  });
}

export { proxy as GET, proxy as POST };
