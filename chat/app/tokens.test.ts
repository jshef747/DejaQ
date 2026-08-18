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

  // ChatApp hand-copies these into SHELL_WIDTH (--shell + TurnShell's 2 x 16px
  // padding), which decides whether the response detail panel can sit beside
  // the reading column without covering or rewrapping it. A token moving here
  // silently makes that decision wrong.
  it("pins the layout tokens the panel-fit constants are derived from", () => {
    const root = block(/^:root \{([\s\S]*?)\n\}/m);
    expect(root["--shell"]).toBe("780px");
    expect(root["--col"]).toBe("704px");
    expect(root["--rail"]).toBe("52px");
    expect(root["--gutter"]).toBe("24px");
  });
});
