import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import path from "path";

// The mockup's :root block is generated from tokens.json; the app copies it verbatim.
const MOCKUP = path.resolve(__dirname, "../../../docs/redesign/ui/soft-orbit/mockup.html");
const TOKENS = path.resolve(__dirname, "./tokens.css");

function declarations(css: string): string[] {
  const start = css.indexOf("/* @tokens:start");
  const end = css.indexOf("/* @tokens:end */");
  const block = css.slice(start, end);
  return block
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l.startsWith("--") || l.startsWith("color-scheme"));
}

describe("Soft Orbit tokens", () => {
  it("match the approved mockup's generated :root block", () => {
    const fromMockup = declarations(readFileSync(MOCKUP, "utf8"));
    const fromApp = declarations(readFileSync(TOKENS, "utf8"));
    expect(fromMockup.length).toBeGreaterThan(150);
    expect(fromApp).toEqual(fromMockup);
  });
});
