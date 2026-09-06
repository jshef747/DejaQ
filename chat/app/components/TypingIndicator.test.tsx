import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import TypingIndicator from "./TypingIndicator";

// Regression coverage for the missing chat-animation bug: a thumbs-down
// escalation used to render nothing at all (ChatApp.handleFeedback never
// touched the generating state TypingIndicator reads), so these lock in the
// escalation wait strip for both tiers plus, unchanged, both non-escalated
// baselines that already worked.

describe("TypingIndicator — escalation tiers", () => {
  it("names the local model for a cache-answer escalation", () => {
    const html = renderToStaticMarkup(
      <TypingIndicator route="local" modelUsed={null} sinceMs={Date.now()} escalating />,
    );
    expect(html).toContain("Escalating to");
    expect(html).toContain("the local model");
    // The handoff row (the same look a fresh local generation ends up in)
    // is present from the start, not appended later by a JS timer.
    expect(html).toContain("Generating on");
    expect(html).toContain("dq-escalation-intro");
    expect(html).toContain("dq-escalation-handoff");
  });

  it("names the external provider for a local-answer escalation", () => {
    const html = renderToStaticMarkup(
      <TypingIndicator route="cloud" modelUsed={null} sinceMs={Date.now()} escalating />,
    );
    expect(html).toContain("Escalating to");
    expect(html).toContain("the external provider");
    expect(html).toContain("Generating on");
  });

  it("falls back to the neutral checking-cache state when escalating but the route isn't known", () => {
    // Defensive: ChatApp only ever mounts escalating=true with a resolved
    // route (see generation-state.startEscalation), but the component must
    // not crash or invent a destination if it somehow did not.
    const html = renderToStaticMarkup(<TypingIndicator route={null} modelUsed={null} sinceMs={null} escalating />);
    expect(html).toContain("Checking cache");
    expect(html).not.toContain("Escalating to");
  });
});

describe("TypingIndicator — normal (non-escalated) baselines, unchanged", () => {
  it("shows the local generating strip for a fresh local answer", () => {
    const html = renderToStaticMarkup(
      <TypingIndicator route="local" modelUsed="gemma4:e4b" sinceMs={Date.now()} />,
    );
    expect(html).toContain("Cache checked");
    expect(html).toContain("No stored answer close enough");
    expect(html).toContain("gemma4:e4b");
    expect(html).not.toContain("Escalating to");
  });

  it("shows the cloud generating strip for a fresh external answer", () => {
    const html = renderToStaticMarkup(
      <TypingIndicator route="cloud" modelUsed="gpt-5.1" sinceMs={Date.now()} />,
    );
    expect(html).toContain("Cache checked");
    expect(html).toContain("gpt-5.1");
    expect(html).not.toContain("Escalating to");
  });

  it("shows the neutral state before any route is known", () => {
    const html = renderToStaticMarkup(<TypingIndicator route={null} modelUsed={null} sinceMs={null} />);
    expect(html).toContain("Checking cache");
  });
});
