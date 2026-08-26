import type { RagDocument } from "./chat-api";

// One row of the `@` dropdown. A repository imported into the knowledge base is
// one document PER FILE sharing one `group_key`, which would otherwise flood
// the picker with hundreds of loose files; rows sharing a key collapse into one
// expandable repository entry, the same shape the dashboard's catalog uses.
// Both levels are referenceable: the repository scopes retrieval to every file
// in it, a file scopes it to that file alone.
export type MentionRow =
  // `expanded` is whether this row's files are actually SHOWN below it, which
  // is not the same as the user having opened it: a query reveals matching
  // files inside a closed repository. The chevron reads this, not the open set,
  // so it never points "closed" above visible children.
  | { kind: "group"; key: string; label: string; count: number; expanded: boolean }
  | { kind: "file"; doc: RagDocument; nested: boolean };

// Rows, not documents: an expanded repository contributes its own row plus one
// per file it reveals. The dropdown scrolls, so this is a ceiling on how much is
// worth rendering at all, not on how much fits.
export const MAX_MENTION_ROWS = 40;

// "github:owner/repo" is the storage key; "owner/repo" is what a person reads.
export function groupLabel(groupKey: string): string {
  return groupKey.replace(/^github:/, "");
}

export function buildMentionRows(
  docs: RagDocument[],
  rawQuery: string,
  expanded: Set<string>,
): MentionRow[] {
  const query = rawQuery.trim().toLowerCase();
  const matches = (text: string) => !query || text.toLowerCase().includes(query);
  // Preserve the server's ordering for ungrouped documents, and put each group
  // where its first member appeared.
  const groups = new Map<string, RagDocument[]>();
  const order: (string | RagDocument)[] = [];
  for (const doc of docs) {
    if (!doc.groupKey) {
      order.push(doc);
      continue;
    }
    let members = groups.get(doc.groupKey);
    if (!members) {
      members = [];
      groups.set(doc.groupKey, members);
      order.push(doc.groupKey);
    }
    members.push(doc);
  }

  const rows: MentionRow[] = [];
  for (const item of order) {
    if (typeof item !== "string") {
      if (matches(item.title)) rows.push({ kind: "file", doc: item, nested: false });
      continue;
    }
    const label = groupLabel(item);
    const files = [...(groups.get(item) ?? [])].sort((a, b) => a.title.localeCompare(b.title));
    const matching = files.filter((f) => matches(f.title));
    if (!matches(label) && matching.length === 0) continue;
    // Typing part of a file name auto-reveals the matches inside a collapsed
    // repository — otherwise the only hit is hidden behind a closed row.
    const children = expanded.has(item)
      ? (query ? matching : files)
      : (query && matching.length ? matching : []);
    rows.push({
      kind: "group", key: item, label, count: files.length,
      expanded: children.length > 0,
    });
    for (const file of children) rows.push({ kind: "file", doc: file, nested: true });
  }
  return rows.slice(0, MAX_MENTION_ROWS);
}
