// Word-level diff for the "why it matched" panel: which words in the typed
// query and the stored query differ. A plain LCS over words (not chars) —
// exact words cancel, leftovers are what changed. Small inputs (one
// sentence each), so the O(n*m) table is nowhere near a cost concern.

export interface DiffWord {
  text: string;
  changed: boolean;
}

function tokenize(s: string): string[] {
  return s.match(/\S+/g) ?? [];
}

function diffTokens(a: string[], b: string[]): { a: DiffWord[]; b: DiffWord[] } {
  const n = a.length;
  const m = b.length;
  const lcs: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i][j] =
        a[i].toLowerCase() === b[j].toLowerCase() ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const outA: DiffWord[] = [];
  const outB: DiffWord[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i].toLowerCase() === b[j].toLowerCase()) {
      outA.push({ text: a[i], changed: false });
      outB.push({ text: b[j], changed: false });
      i++;
      j++;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      outA.push({ text: a[i], changed: true });
      i++;
    } else {
      outB.push({ text: b[j], changed: true });
      j++;
    }
  }
  while (i < n) outA.push({ text: a[i++], changed: true });
  while (j < m) outB.push({ text: b[j++], changed: true });
  return { a: outA, b: outB };
}

/** Diff the typed query against the stored one, word by word. */
export function diffQueries(typed: string, stored: string): { typed: DiffWord[]; stored: DiffWord[] } {
  const { a, b } = diffTokens(tokenize(typed), tokenize(stored));
  return { typed: a, stored: b };
}

// x-dejaq-cache-matched-query is a diagnostic header, not the stored text:
// the server collapses whitespace and hard-truncates it at 200 characters
// with no ellipsis (openai_compat.py _diagnostic_prompt). The value itself
// is percent-encoded on the wire and decoded back exactly server-side
// (_encode_header_text) and client-side (decodeURIComponent in
// chat-api.ts), so truncation is the only way it can still differ from the
// real stored text. Diffing a truncated value would underline a cut-off
// tail word as "changed" when it was never typed differently.
//
// Truncation shows in the length alone: the value is whitespace-collapsed
// before the cut, so only a truncated one reaches the limit.
const HEADER_TRUNCATE_LIMIT = 200;

export function isLossyHeaderText(stored: string): boolean {
  return stored.length >= HEADER_TRUNCATE_LIMIT;
}
