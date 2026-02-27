import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // globe.gl and its dependencies are ESM-only; transpile them for Next.js
  transpilePackages: ["globe.gl", "three-globe", "three"],
};

export default nextConfig;
