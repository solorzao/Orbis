# Globe land data

`land-110m.v1.geojson` is the globe's dotted land: Natural Earth 1:110m admin-0 countries
(public domain, naturalearthdata.com) as shipped in three-globe 2.45.0
(`example/country-polygons/ne_110m_admin_0_countries.geojson`), slimmed to the ISO_A2 code and
the geometry, without Antarctica.

Rebuild it with `node scripts/slim-geojson.mjs` (a test checks the file matches). `/geo/` is
served with `Cache-Control: public, max-age=31536000, immutable`, so a changed file needs a new
version in its name and in `LAND_URL` (`src/components/Globe.tsx`).
