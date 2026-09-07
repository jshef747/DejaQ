// Builds and ships the per-conversation "session log" - a human-readable
// questions-and-answers.md written to disk on the machine running this chat
// app (via /api/session-log), independent of where the DejaQ server or
// dashboard run (see chat/README.md's server/key override notes). One record
// per turn. Every field here is read straight off what the pipeline already
// reports through sendChatMessage/ChatSuccess (chat-api.ts) - nothing is
// guessed, inferred, or produced by an extra model call. A field the pipeline
// does not expose on a given path is reported as "Not available"/"Not run",
// never silently omitted or invented.

export type TurnOutcome = "success" | "api_error" | "empty_answer" | "stopped";

export interface RawTurnInput {
  turnNumber: number;
  timestampMs: number;
  originalQuestion: string;
  attachmentName: string | null;
  attachmentKind: string | null;
  ragDocumentTitle: string | null;
  outcome: TurnOutcome;
  errorMessage: string | null;
  answerText: string;
  tier: "cache" | "local" | "external" | null;
  modelUsed: string | null;
  cacheDistance: number | null;
  cacheMatchedQuery: string | null;
  cacheEnrichedQuery: string | null;
  validatorVerdict: string | null;
  nearestCacheDistance: number | null;
  nearestCacheQuery: string | null;
  promptDifficulty: string | null;
  promptDifficultyScore: number | null;
  latencyMs: number | null;
  finishStatus: "completed" | "incomplete" | "failed" | null;
  failureMessage: string | null;
  serverPromptTokens: number | null;
  serverCompletionTokens: number | null;
  ragChunks: number | null;
  answerAuthored: string | null;
}

const NOT_AVAILABLE = "Not available";
const NOT_RUN = "Not run";
const NONE = "None";

function fmtDistance(n: number | null): string {
  return n === null ? NONE : n.toFixed(4);
}

export function outcomeLabel(t: RawTurnInput): string {
  switch (t.outcome) {
    case "api_error":
      return `Error - request failed: ${t.errorMessage || "unknown error"}`;
    case "empty_answer":
      return "Error - server returned HTTP 200 with no answer text";
    case "stopped":
      return "Partial answer - stopped by user before the stream finished";
    case "success":
      if (t.errorMessage) return `Partial answer - stream did not finish cleanly: ${t.errorMessage}`;
      if (t.finishStatus === "incomplete") return "Partial answer - cut off by the max-token budget";
      if (t.finishStatus === "failed") return `Error - generation failed: ${t.failureMessage || "unknown error"}`;
      if (t.tier === "cache") return "Success - cache hit";
      if (t.tier === "local") return "Success - cache miss, answered by local model";
      if (t.tier === "external") return "Success - cache miss, answered by external model";
      return "Success";
    default:
      return NOT_AVAILABLE;
  }
}

function attachmentLabel(t: RawTurnInput): string {
  if (!t.attachmentName) return NONE;
  return `${t.attachmentName} (${t.attachmentKind ?? "unknown type"})`;
}

// null here is a documented, meaningful state (chat-api.ts: "null only when
// there was nothing to rewrite"), not a missing value - the two must read
// differently to someone auditing the log.
function enrichedQuestionLabel(t: RawTurnInput): string {
  if (t.outcome === "api_error") return NOT_AVAILABLE;
  if (t.cacheEnrichedQuery === null) {
    return `${NONE} (no rewrite - the enricher returned the question unchanged, or enrichment did not run)`;
  }
  return t.cacheEnrichedQuery;
}

function cacheDiagnosticsLines(t: RawTurnInput): string[] {
  const lines: string[] = [];
  if (t.tier === "cache") {
    lines.push(`- **Cache distance:** ${fmtDistance(t.cacheDistance)}`);
    lines.push(`- **Matched cached question:** ${t.cacheMatchedQuery ?? NONE}`);
    lines.push(`- **Human-authored answer:** ${t.answerAuthored === "human" ? "Yes" : "No"}`);
  } else {
    lines.push(
      `- **Nearest cached question distance:** ${
        t.nearestCacheDistance !== null ? fmtDistance(t.nearestCacheDistance) : `${NONE} (no near-miss candidate reported)`
      }`,
    );
    lines.push(`- **Nearest cached question:** ${t.nearestCacheQuery ?? NONE}`);
  }
  lines.push(`- **Validator result:** ${t.validatorVerdict ?? `${NOT_RUN} (no candidate reached the validator)`}`);
  return lines;
}

function difficultyLines(t: RawTurnInput): string[] {
  if (t.tier === "cache") {
    // Never substitute a cached/stale score here - the classifier does not
    // run again on a hit at all (CLAUDE.md).
    return [`- **Difficulty classification:** ${NOT_RUN} (cache hit - the classifier only runs on a genuine cache miss)`];
  }
  if (t.promptDifficulty === null) {
    return [`- **Difficulty classification:** ${NOT_AVAILABLE}`];
  }
  return [
    `- **Difficulty label:** ${t.promptDifficulty}`,
    `- **Difficulty raw score:** ${t.promptDifficultyScore !== null ? t.promptDifficultyScore.toFixed(4) : NOT_AVAILABLE}`,
  ];
}

function tokenLines(t: RawTurnInput): string[] {
  if (t.serverPromptTokens === null && t.serverCompletionTokens === null) {
    return [`- **Token counts:** ${NOT_AVAILABLE} (no terminal stream event reported usage - see Outcome above)`];
  }
  const provenance =
    t.tier === "external" ? "provider-reported" : "server-side word-count estimate, not an exact count (see CLAUDE.md)";
  return [
    `- **Prompt tokens:** ${t.serverPromptTokens ?? NOT_AVAILABLE} (${provenance})`,
    `- **Completion tokens:** ${t.serverCompletionTokens ?? NOT_AVAILABLE} (${provenance})`,
  ];
}

export function renderTurnMarkdown(t: RawTurnInput): string {
  const ts = new Date(t.timestampMs).toISOString();
  const lines: string[] = [];
  lines.push(`## Turn ${t.turnNumber} — ${ts}`);
  lines.push("");
  lines.push(`**Outcome:** ${outcomeLabel(t)}`);
  lines.push("");
  lines.push("**Original question:**");
  lines.push("");
  lines.push(t.originalQuestion || `_(${NONE})_`);
  lines.push("");
  lines.push("**Enriched question actually used for the cache lookup:**");
  lines.push("");
  lines.push(enrichedQuestionLabel(t));
  lines.push("");
  lines.push(`**Attachment:** ${attachmentLabel(t)}`);
  if (t.ragDocumentTitle) lines.push(`**Knowledge-base document referenced:** ${t.ragDocumentTitle}`);
  lines.push("");
  lines.push("**Answer actually delivered:**");
  lines.push("");
  lines.push(t.answerText ? t.answerText : `_(${NONE} - no answer text)_`);
  lines.push("");
  lines.push(`- **Answer source:** ${t.tier ?? NOT_AVAILABLE}${t.modelUsed ? ` / model \`${t.modelUsed}\`` : ""}`);
  lines.push(
    `- **Response duration:** ${
      t.latencyMs !== null ? `${t.latencyMs} ms (client-measured: network + full generation)` : NOT_AVAILABLE
    }`,
  );
  lines.push(...cacheDiagnosticsLines(t));
  lines.push(...difficultyLines(t));
  lines.push(`- **Adjustment outcome:** ${NOT_AVAILABLE} (not exposed to the client on any path today)`);
  lines.push(`- **RAG chunks retrieved:** ${t.ragChunks ?? NONE}`);
  lines.push(...tokenLines(t));
  lines.push("");
  lines.push("---");
  lines.push("");
  return lines.join("\n");
}

export function renderSessionHeader(conversationId: string, department: string, createdAtMs: number): string {
  return [
    "# DejaQ session log",
    "",
    `**Session (chat conversation) id:** \`${conversationId}\``,
    `**Department:** \`${department || NOT_AVAILABLE}\``,
    `**Log file created:** ${new Date(createdAtMs).toISOString()}`,
    "",
    "This file covers exactly one browser chat conversation (client-side; the",
    "DejaQ server itself is stateless and keeps no session concept of its own -",
    "see CLAUDE.md). Generated only from fields the DejaQ pipeline already",
    "reports to this chat app; nothing here was inferred, guessed, or produced",
    "by an extra model call.",
    "",
    "---",
    "",
  ].join("\n");
}

// Fire-and-forget: a logging failure must never turn a completed chat turn
// into a visible failure, so every error here is swallowed.
export async function logSessionTurn(conversationId: string, department: string, turn: RawTurnInput): Promise<void> {
  try {
    await fetch("/api/session-log", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversationId, department, turn }),
      keepalive: true,
    });
  } catch {
    // best-effort only
  }
}
