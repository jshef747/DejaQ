import type { Route } from "./provenance";

// One in-flight answer for one conversation, as ChatApp tracks it. A fresh
// send and a thumbs-down escalation replay (ChatApp.handleFeedback) share
// this same shape and the same map — one boundary the wait strip
// (TypingIndicator), the composer lock, and the sidebar's working-dot all
// read, rather than each tracking their own idea of "is this generating".
export interface GenerationState {
  // No content delta has landed yet, so the wait strip is still up. The
  // whole record's presence, not this flag, means "generating".
  waiting: boolean;
  route: Route | null;
  model: string | null;
  sinceMs: number | null;
  // Set for an escalation replay rather than a fresh send — see
  // startEscalation below.
  escalating: boolean;
}

export type GenerationMap = Record<string, GenerationState>;

// Starts the wait strip for a fresh send. Route and model are unknown until
// the stream's headers land, so the wait strip opens on the neutral
// "Checking cache…" state (TypingIndicator) until a later partial update
// fills them in.
export function startSend(map: GenerationMap, convId: string): GenerationMap {
  return { ...map, [convId]: { waiting: true, route: null, model: null, sinceMs: null, escalating: false } };
}

// Starts the wait strip for a thumbs-down escalation replay. Unlike a fresh
// send, the destination is already known from the tier being escalated away
// from (cache -> local, local -> external) — there is no streaming response
// to carry it later, since /v1/feedback is a single non-streaming call — so
// route and the elapsed-counter clock start immediately instead of waiting
// on a signal that will never arrive.
//
// No-ops (returns the map unchanged) when the slot is already taken: a
// fresh send, or another escalation, already owns it for this conversation,
// and this one gets no wait strip of its own rather than stomping on that
// one's record.
export function startEscalation(map: GenerationMap, convId: string, route: Route): GenerationMap {
  if (map[convId]) return map;
  return { ...map, [convId]: { waiting: true, route, model: null, sinceMs: Date.now(), escalating: true } };
}

// Clears the record only if it is still the escalation that started it. A
// fresh send begun for the same conversation while the escalation's
// sendFeedback call was still in flight (the composer is not locked during
// an escalation — see ChatApp's isGenerating) owns the slot now, and this
// must not delete that send's own wait strip mid-generation. This is the
// ordering guard the escalation's completion (a later phase, since fresh
// sends normally finish faster than an escalation replay) must respect: it
// may only clear the phase it started, never one that has since taken its
// place.
export function endEscalation(map: GenerationMap, convId: string): GenerationMap {
  const cur = map[convId];
  if (!cur || !cur.escalating) return map;
  const next = { ...map };
  delete next[convId];
  return next;
}

// Ends generation unconditionally. Used by a fresh send's own completion,
// Stop, and its error paths — all of which own their record outright, since
// nothing else can start a second fresh send for a conversation whose
// composer is already locked by the first one.
export function endGeneration(map: GenerationMap, convId: string): GenerationMap {
  if (!(convId in map)) return map;
  const next = { ...map };
  delete next[convId];
  return next;
}
