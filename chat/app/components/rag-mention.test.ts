import { describe, expect, it } from "vitest";
import { buildMentionRows, groupLabel } from "./rag-mention";
import type { RagDocument } from "./chat-api";

const REPO = "github:acme/widgets";
const doc = (id: number, title: string, groupKey: string | null = null): RagDocument => ({
  id, title, kind: "code", groupKey,
});

const CORPUS: RagDocument[] = [
  doc(1, "Refund policy"),
  doc(2, "src/auth.ts", REPO),
  doc(3, "README.md", REPO),
  doc(4, "src/router.ts", REPO),
];

describe("groupLabel", () => {
  it("strips the storage prefix", () => {
    expect(groupLabel(REPO)).toBe("acme/widgets");
  });
});

describe("buildMentionRows", () => {
  it("collapses a repository into one row, files hidden until expanded", () => {
    const rows = buildMentionRows(CORPUS, "", new Set());
    expect(rows).toEqual([
      { kind: "file", doc: CORPUS[0], nested: false },
      { kind: "group", key: REPO, label: "acme/widgets", count: 3, expanded: false },
    ]);
  });

  it("expands to its files, sorted, when opened", () => {
    const rows = buildMentionRows(CORPUS, "", new Set([REPO]));
    expect(rows.map((r) => (r.kind === "group" ? r.label : r.doc.title))).toEqual([
      "Refund policy", "acme/widgets", "README.md", "src/auth.ts", "src/router.ts",
    ]);
    expect(rows.every((r) => r.kind !== "file" || r.nested === (r.doc.groupKey !== null))).toBe(true);
  });

  it("matches the repository by its label", () => {
    const rows = buildMentionRows(CORPUS, "widgets", new Set());
    expect(rows).toEqual([{ kind: "group", key: REPO, label: "acme/widgets", count: 3, expanded: false }]);
  });

  it("reveals matching files inside a COLLAPSED repository", () => {
    // Otherwise the only hit for "router" is invisible behind a closed row.
    const rows = buildMentionRows(CORPUS, "router", new Set());
    expect(rows).toEqual([
      // Chevron must read "open" — its match is visible below it.
      { kind: "group", key: REPO, label: "acme/widgets", count: 3, expanded: true },
      { kind: "file", doc: CORPUS[3], nested: true },
    ]);
  });

  it("drops a repository whose label and files both miss", () => {
    expect(buildMentionRows(CORPUS, "refund", new Set())).toEqual([
      { kind: "file", doc: CORPUS[0], nested: false },
    ]);
  });

  it("caps the row count so a huge repository cannot flood the dropdown", () => {
    const big = Array.from({ length: 500 }, (_, i) => doc(i + 10, `file-${i}.py`, REPO));
    expect(buildMentionRows(big, "", new Set([REPO])).length).toBe(40);
  });
});
