// Builds public/geo/land-110m.v1.geojson, the globe's dotted land, from the
// Natural Earth 1:110m countries that ship with three-globe (public domain).
// Keeps only ISO_A2 and the geometry, and drops Antarctica.
//
//   node scripts/slim-geojson.mjs
//
// If the output changes, bump the version in the file name (and LAND_URL in
// src/components/Globe.tsx): /geo/ is served with an immutable cache header.
import { readFileSync, writeFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

export const SOURCE = path.resolve(
  here,
  "../node_modules/three-globe/example/country-polygons/ne_110m_admin_0_countries.geojson",
);
export const TARGET = path.resolve(here, "../public/geo/land-110m.v1.geojson");

/** Only what the globe reads: the ISO_A2 code (to drop Antarctica) and the shape. */
export function slimLand(collection) {
  return {
    type: "FeatureCollection",
    features: collection.features
      .filter((f) => f.properties.ISO_A2 !== "AQ")
      .map((f) => ({
        type: "Feature",
        properties: { ISO_A2: f.properties.ISO_A2 },
        geometry: f.geometry,
      })),
  };
}

/** The file's exact contents. */
export function build() {
  return `${JSON.stringify(slimLand(JSON.parse(readFileSync(SOURCE, "utf8"))))}\n`;
}

const size = (buf) => `${buf.length} B raw, ${gzipSync(buf, { level: 9 }).length} B gzipped`;

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const out = build();
  writeFileSync(TARGET, out);
  console.log(`source: ${size(readFileSync(SOURCE))}`);
  console.log(`output: ${size(Buffer.from(out))} -> ${path.relative(process.cwd(), TARGET)}`);
}
