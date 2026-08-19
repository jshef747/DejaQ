import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// The light palette is written twice on purpose - a media query cannot appear
// in a selector list, so the prefers-color-scheme block and the forced
// [data-theme="light"] block each carry the whole thing. Drift between them
// is silent: one theme path keeps working while the other goes stale.
const css = readFileSync(join(__dirname, "tokens.css"), "utf8");

function declarations(block: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [, prop, value] of block.matchAll(/(--[\w-]+|color-scheme)\s*:\s*([^;]+);/g)) {
    out[prop] = value.trim();
  }
  return out;
}

function block(pattern: RegExp): Record<string, string> {
  const match = css.match(pattern);
  if (!match) throw new Error(`token block not found: ${pattern}`);
  return declarations(match[1]);
}

describe("tokens.css", () => {
  it("keeps the two light palettes in step", () => {
    const media = block(
      /@media \(prefers-color-scheme: light\) \{\s*:root:not\(\[data-theme="dark"\]\) \{([\s\S]*?)\n {2}\}\n\}/,
    );
    const forced = block(/:root\[data-theme="light"\] \{([\s\S]*?)\n\}/);

    expect(Object.keys(media).length).toBeGreaterThan(20);
    expect(forced).toEqual(media);
  });
});
