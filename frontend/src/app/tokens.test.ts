import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import path from "path";

// The mockup's :root block is generated from tokens.json; the app copies it verbatim.
const MOCKUP = path.resolve(__dirname, "../../../docs/redesign/ui/soft-orbit/mockup.html");
const TOKENS = path.resolve(__dirname, "./tokens.css");
const GLOBALS = path.resolve(__dirname, "./globals.css");
const PRIMITIVES = path.resolve(__dirname, "./soft-orbit.css");

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

  it("are unlayered, so they override Tailwind's layered theme defaults", () => {
    expect(readFileSync(TOKENS, "utf8")).not.toMatch(/@layer/);
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

describe("Soft Orbit primitives", () => {
  const css = () => readFileSync(PRIMITIVES, "utf8");

  // Layout code builds on these; a refactor must not drop one silently.
  it.each([".glass", ".pill", ".seg", ".aurora-btn", ".pillbar", ".low-power .glass"])(
    "soft-orbit.css defines %s",
    (selector) => {
      const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      // The selector starts a rule or a selector list entry: "<sel> {" or "<sel>,".
      expect(css()).toMatch(new RegExp(`(^|[\\s,}])${escaped}\\s*[,{]`, "m"));
    },
  );

  // In the components layer, so a Tailwind utility on the same element still wins.
  it("is imported by globals.css after the tokens, in the components layer", () => {
    const globals = readFileSync(GLOBALS, "utf8");
    const tokens = globals.indexOf('@import "./tokens.css";');
    const primitives = globals.indexOf('@import "./soft-orbit.css" layer(components);');
    expect(tokens).toBeGreaterThan(-1);
    expect(primitives).toBeGreaterThan(tokens);
  });

  it("drops the mockup's fixed placement from .glass (layout grids place panels)", () => {
    const glass = css().match(/^\.glass\s*\{([^}]*)\}/m)?.[1] ?? "";
    expect(glass).not.toBe("");
    expect(glass).not.toMatch(/position\s*:/);
    expect(glass).not.toMatch(/z-index\s*:/);
  });
});
