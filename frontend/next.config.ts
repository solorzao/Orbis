import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // globe.gl and its dependencies are ESM-only; transpile them for Next.js
  transpilePackages: ["globe.gl", "three-globe", "three"],
  // Files in public/geo are versioned by name (land-110m.v1.geojson), so they never change.
  async headers() {
    return [
      {
        source: "/geo/:path*",
        headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }],
      },
    ];
  },
};

export default nextConfig;
