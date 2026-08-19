// Edit & Save — the rules about a draft, kept out of the component so they can
// be tested without rendering one.

/** Whether a draft is worth sending: non-empty and actually different.
 *
 * Trailing whitespace is ignored on both sides, so re-saving an untouched
 * answer that happens to end in a newline is still a no-op rather than a
 * pointless cache write. Interior whitespace is NOT normalised — a person who
 * re-spaced a list changed the answer, and the whole point of the feature is
 * that what they typed is what gets stored.
 */
export function canSave(original: string, draft: string): boolean {
  if (!draft.trim()) return false;
  return draft.trimEnd() !== original.trimEnd();
}

/** The text actually sent. Trailing whitespace goes; nothing else is touched. */
export function normalizeDraft(draft: string): string {
  return draft.trimEnd();
}

/** Whether Cmd/Ctrl+Enter was pressed — the save binding inside the editor. */
export function isSaveShortcut(e: {
  key: string;
  metaKey: boolean;
  ctrlKey: boolean;
  altKey: boolean;
}): boolean {
  return (e.metaKey || e.ctrlKey) && !e.altKey && e.key === "Enter";
}

/** Whether the server actually wrote the edit to the cache.
 *
 * Load-bearing for the thumbs row: on "not_cached"/"message_mismatch" the
 * server skips scoring entirely, so showing the terminal thumbs-up would both
 * claim a +1.0 that was never applied AND remove the only control left for
 * rating the answer.
 */
export function editLanded(status: string | null | undefined): boolean {
  return status === "saved" || status === "created";
}

/** What the user is told after a save, by the server's edit_status.
 *
 * Null means "nothing worth interrupting for" — the ordinary success case
 * already shows in the transcript. The other three all mean the text is on
 * screen but NOT in the cache, and saying so plainly is the point: a silent
 * no-op would leave the user believing they had corrected it for everyone.
 */
export function editStatusNotice(
  status: string | null | undefined,
): { kind: "success" | "info"; title: string; body: string } | null {
  switch (status) {
    case "saved":
    case "created":
      return {
        kind: "success",
        title: "Saved",
        body: "This is now the cached answer — the next person to ask gets your version.",
      };
    case "not_cached":
      return {
        kind: "info",
        title: "Kept here only",
        body: "Your edit is in this conversation, but there was no cache entry to update. Answers about an attachment can only be corrected while their entry exists.",
      };
    case "message_mismatch":
      return {
        kind: "info",
        title: "Kept here only",
        body: "Your edit is in this conversation. It was not cached because the saved request context no longer matches.",
      };
    default:
      return null;
  }
}
