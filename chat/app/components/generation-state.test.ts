import { describe, expect, it } from "vitest";
import { startSend, startEscalation, endEscalation, endGeneration } from "./generation-state";

describe("startSend", () => {
  it("opens with no route known yet - it arrives with the stream's headers", () => {
    const map = startSend({}, "c1");
    expect(map.c1).toEqual({ waiting: true, route: null, model: null, sinceMs: null, escalating: false });
  });
});

describe("startEscalation", () => {
  it("opens with the destination and elapsed clock already known - no headers to wait on", () => {
    const before = Date.now();
    const map = startEscalation({}, "c1", "local");
    expect(map.c1.waiting).toBe(true);
    expect(map.c1.route).toBe("local");
    expect(map.c1.escalating).toBe(true);
    expect(map.c1.model).toBeNull();
    expect(map.c1.sinceMs).toBeGreaterThanOrEqual(before);
  });

  it("names the cloud destination for a local-answer escalation", () => {
    const map = startEscalation({}, "c1", "cloud");
    expect(map.c1.route).toBe("cloud");
  });

  it("does not stomp a slot a fresh send already owns", () => {
    const sent = startSend({}, "c1");
    const map = startEscalation(sent, "c1", "local");
    expect(map).toBe(sent);
    expect(map.c1.escalating).toBe(false);
  });

  it("does not stomp a slot another escalation already owns", () => {
    const first = startEscalation({}, "c1", "local");
    const map = startEscalation(first, "c1", "cloud");
    expect(map).toBe(first);
  });
});

describe("endEscalation - the state-ordering guard", () => {
  it("clears a slot it owns", () => {
    const started = startEscalation({}, "c1", "local");
    const ended = endEscalation(started, "c1");
    expect(ended.c1).toBeUndefined();
  });

  it("never clears a fresh send that took the slot after the escalation started", () => {
    // The captain's exact race: a thumbs-down escalation starts (no
    // AbortController, so nothing blocks the composer), the user sends a
    // new message before it resolves, and only then does the escalation's
    // sendFeedback call finally come back and try to release its slot.
    let map = startEscalation({}, "c1", "local");
    map = startSend(map, "c1"); // a later phase takes the slot
    const afterEscalationCompletes = endEscalation(map, "c1");
    expect(afterEscalationCompletes).toBe(map); // unchanged - not cleared too early
    expect(afterEscalationCompletes.c1.waiting).toBe(true);
    expect(afterEscalationCompletes.c1.escalating).toBe(false);
  });

  it("no-ops on an empty map", () => {
    expect(endEscalation({}, "c1")).toEqual({});
  });
});

describe("endGeneration", () => {
  it("clears whatever record is present, escalating or not", () => {
    expect(endGeneration(startSend({}, "c1"), "c1").c1).toBeUndefined();
    expect(endGeneration(startEscalation({}, "c1", "local"), "c1").c1).toBeUndefined();
  });

  it("no-ops when nothing is generating", () => {
    const map = {};
    expect(endGeneration(map, "c1")).toBe(map);
  });

  it("leaves other conversations untouched", () => {
    const map = { ...startSend({}, "a"), ...startSend({}, "b") };
    const next = endGeneration(map, "a");
    expect(next.a).toBeUndefined();
    expect(next.b).toBeDefined();
  });
});
