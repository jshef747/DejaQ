/** Draft answers get the same per-block reading direction ordinary answers do.
 *
 * DraftChooser reuses `MarkdownContent` from ChatMessage rather than wiring its
 * own ReactMarkdown, so a code block or a KaTeX formula cannot render
 * differently depending on whether the answer arrived as a draft. The direction
 * heuristic rides along with that reuse - which is the thing worth pinning,
 * because it is exactly what a careless merge resolution loses: this branch
 * exports MarkdownContent, and `staging` had rewritten it to wrap each block in
 * `directional()`. Export the pre-rewrite version instead and drafts silently
 * become left-to-right for every Hebrew answer.
 *
 * Rendered with renderToStaticMarkup - no DOM, no new dependency.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import DraftChooser from "./DraftChooser";
import type { Draft } from "./chat-api";

const HEBREW = "כדי לאפס את הסיסמה יש להיכנס להגדרות החשבון.";
const ENGLISH = "Reset your password from the account settings page.";

function render(first: string, second: string) {
  const drafts: Draft[] = [
    { label: "A", responseId: "demo--default:a", content: first, distance: 0 },
    { label: "B", responseId: "demo--default:b", content: second, distance: 0.014 },
  ];
  return renderToStaticMarkup(
    <DraftChooser drafts={drafts} busy={false} onChoose={() => {}} />,
  );
}

describe("DraftChooser reading direction", () => {
  it("renders a Hebrew draft right-to-left", () => {
    expect(render(HEBREW, ENGLISH)).toContain(`dir="rtl"`);
  });

  it("leaves an English draft left-to-right", () => {
    const html = render(ENGLISH, HEBREW);
    expect(html).not.toContain(`dir="rtl"`);
    expect(html).toContain(`dir="ltr"`);
  });

  it("decides per draft, not once for the pair", () => {
    // Only the shown draft is rendered, so the direction follows the tab.
    expect(render(HEBREW, ENGLISH)).toContain(HEBREW);
    expect(render(ENGLISH, HEBREW)).not.toContain(HEBREW);
  });
});
