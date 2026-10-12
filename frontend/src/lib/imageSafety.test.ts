import { describe, it, expect } from "vitest";
import { MIN_PHOTO_WIDTH, looksLikePhoto, safeImageUrl, veilsImage } from "./imageSafety";

describe("safeImageUrl", () => {
  it("keeps a public https photo URL", () => {
    expect(safeImageUrl("https://cdn.example.com/2026/10/storm-port.jpg")).toBe(
      "https://cdn.example.com/2026/10/storm-port.jpg",
    );
  });

  it.each([
    ["http", "http://cdn.example.com/a.jpg"],
    ["data", "data:image/png;base64,AAAA"],
    ["javascript", "javascript:alert(1)"],
    ["protocol-relative", "//cdn.example.com/a.jpg"],
    ["not a URL", "a.jpg"],
    ["empty", ""],
    ["null", null],
    ["undefined", undefined],
  ])("drops a non-https URL (%s)", (_, url) => {
    expect(safeImageUrl(url)).toBeNull();
  });

  it.each([
    "https://cdn.example.com/static/logo.png",
    "https://cdn.example.com/brand/Site-Logo-2x.png",
    "https://cdn.example.com/img/site_logo.png",
    "https://cdn.example.com/logos/reuters.png",
    "https://cdn.example.com/logo2x.png",
    "https://example.com/favicon.ico",
    "https://cdn.example.com/img/placeholder.jpg",
    "https://cdn.example.com/default-image.jpg",
    "https://cdn.example.com/default_image.png",
    "https://cdn.example.com/defaultimage.png",
  ])("drops a URL that looks like a logo or a stand-in: %s", (url) => {
    expect(safeImageUrl(url)).toBeNull();
  });

  it.each([
    "https://logo.example.com/2026/10/storm.jpg", // the host isn't the image
    "https://cdn.example.com/es/psicologo-clinico.jpg", // a word that contains logo
    "https://cdn.example.com/a.jpg?fallback=default-image.jpg", // the query isn't the image
    "https://cdn.example.com/catalogue/flood.jpg",
  ])("keeps a photo whose URL only mentions a logo outside its path's words: %s", (url) => {
    expect(safeImageUrl(url)).toBe(url);
  });
});

describe("looksLikePhoto", () => {
  it("accepts a photo-sized image", () => {
    expect(looksLikePhoto(640, 360)).toBe(true);
    expect(looksLikePhoto(MIN_PHOTO_WIDTH, 100)).toBe(true);
    expect(looksLikePhoto(400, 800)).toBe(true); // 0.5, a portrait at the limit
    expect(looksLikePhoto(900, 300)).toBe(true); // 3, a wide one at the limit
  });

  it("rejects a tiny image (an icon or a tracking pixel)", () => {
    expect(looksLikePhoto(MIN_PHOTO_WIDTH - 1, 90)).toBe(false);
    expect(looksLikePhoto(1, 1)).toBe(false);
  });

  it("rejects an odd aspect ratio (a banner or a strip)", () => {
    expect(looksLikePhoto(1200, 200)).toBe(false); // 6
    expect(looksLikePhoto(300, 900)).toBe(false); // 0.33
  });

  it("rejects an image with no size", () => {
    expect(looksLikePhoto(0, 0)).toBe(false);
    expect(looksLikePhoto(640, 0)).toBe(false);
  });
});

describe("veilsImage", () => {
  it("blurs a sensitive lead's image (conflict in any of its tags) until revealed", () => {
    expect(veilsImage(true, false)).toBe(true);
    expect(veilsImage(true, true)).toBe(false);
  });

  it("shows any other lead's image", () => {
    expect(veilsImage(false, false)).toBe(false);
  });
});
