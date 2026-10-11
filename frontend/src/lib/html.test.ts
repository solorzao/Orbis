import { describe, it, expect } from "vitest";
import { escapeHtml } from "./html";

describe("escapeHtml", () => {
  it.each([
    ["&", "&amp;"],
    ["<", "&lt;"],
    [">", "&gt;"],
    ['"', "&quot;"],
    ["'", "&#39;"],
  ])("escapes %s", (raw, escaped) => {
    expect(escapeHtml(raw)).toBe(escaped);
  });

  it("neutralises markup in a place name", () => {
    expect(escapeHtml(`<img src=x onerror="alert('x')">Paris & Co`)).toBe(
      "&lt;img src=x onerror=&quot;alert(&#39;x&#39;)&quot;&gt;Paris &amp; Co",
    );
  });

  it("escapes & first, so entities aren't double-decoded", () => {
    expect(escapeHtml("&lt;")).toBe("&amp;lt;");
  });

  it("leaves plain text alone", () => {
    expect(escapeHtml("São Paulo, Brazil")).toBe("São Paulo, Brazil");
    expect(escapeHtml("")).toBe("");
  });
});
