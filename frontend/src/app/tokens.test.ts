import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import path from "path";

// The mockup's :root block is generated from tokens.json; the app copies it verbatim.
const MOCKUP = path.resolve(__dirname, "../../../docs/redesign/ui/soft-orbit/mockup.html");
const TOKENS = path.resolve(__dirname, "./tokens.css");
const GLOBALS = path.resolve(__dirname, "./globals.css");

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

  // next/font puts the self-hosted families on <html> under hashed names; these
  // lines point the token stacks at them. Without them the app falls back to
  // whatever Space Grotesk / Orbitron the visitor happens to have installed.
  it.each([
    "--font-brand: var(--font-orbitron), Orbitron, sans-serif;",
    '--font-heading: var(--font-space-grotesk), "Space Grotesk", system-ui, sans-serif;',
    '--font-body: var(--font-space-grotesk), "Space Grotesk", system-ui, sans-serif;',
    '--font-mono: var(--font-jetbrains-mono), "JetBrains Mono", ui-monospace, monospace;',
  ])("globals.css points the token font stack at the self-hosted font: %s", (line) => {
    const globals = readFileSync(GLOBALS, "utf8")
      .split("\n")
      .map((l) => l.trim());
    expect(globals).toContain(line);
  });
});
