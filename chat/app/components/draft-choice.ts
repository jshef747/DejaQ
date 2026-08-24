// Alternative drafts - the rules about keeping one, kept out of the component
// so they can be tested without rendering one. Mirrors edit-draft.ts.

import type { Draft } from "./chat-api";

/** Whether a turn is still waiting on a choice.
 *
 * Two conditions, both load-bearing. A single draft is not a choice (the server
 * never sends one, but a truncated or hand-edited stored conversation could).
 * And a turn whose choice is already made must never ask again - that is what
 * makes the answer survive a reload as an answer rather than as a question.
 */
export function hasPendingDrafts(message: {
  drafts?: Draft[] | null;
  chosenDraftLabel?: "A" | "B" | null;
}): boolean {
  return Boolean(message.drafts && message.drafts.length > 1 && !message.chosenDraftLabel);
}

/** The drafts NOT kept, by response id.
 *
 * Compared on responseId rather than label so the answer text is never the
 * thing identifying an entry - two drafts could in principle carry the same
 * label after a malformed response, but the id is what the server scores.
 */
export function rejectedDraftIds(drafts: Draft[], kept: Draft): string[] {
  return drafts.filter((d) => d.responseId !== kept.responseId).map((d) => d.responseId);
}

/** The response id to hold onto after a pick.
 *
 * Prefer the server's, always: an alias-served id redirects to its root, so
 * later feedback or an edit on this turn would otherwise address an entry that
 * no longer holds this text. Falls back to the picked draft's own id only when
 * the server returned none.
 */
export function adoptedResponseId(
  serverResponseId: string | null,
  kept: Draft,
): string {
  return serverResponseId ?? kept.responseId;
}

/** What the user is told after a pick.
 *
 * Null for the ordinary success case - the transcript collapsing to the chosen
 * answer already says it worked, and a toast for every pick would be noise.
 * "not_found" is worth saying out loud: the answer is on screen but the choice
 * changed nothing, so a user who expected to have taught the cache something
 * should not be left believing they did.
 */
export function draftChoiceNotice(
  status: string | null | undefined,
): { kind: "info"; title: string; body: string } | null {
  if (status === "not_found") {
    return {
      kind: "info",
      title: "Choice not saved",
      body: "That answer was removed from the cache before your pick landed. You still have the answer you chose.",
    };
  }
  return null;
}
