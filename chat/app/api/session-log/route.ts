import { NextRequest, NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";
import { renderSessionHeader, renderTurnMarkdown, type RawTurnInput } from "../../components/session-log";

// Session logs live on THIS machine's disk (wherever `npm run dev` for chat/
// runs), never on the DejaQ server/dashboard machine - that is the whole
// point: "View session log" / "Download log" must work even when the DejaQ
// backend is remote. See chat/README.md for the server-override story this
// mirrors.
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const LOG_ROOT = path.join(process.cwd(), ".session-logs");
// Matches exactly the id shape ChatApp.tsx generates (`conv_${Date.now()}`).
// A strict allowlist, not a sanitizer - anything else is rejected outright,
// which is what keeps this route from ever reading or writing outside
// LOG_ROOT (no arbitrary filesystem access, no path traversal).
const CONV_ID_RE = /^conv_[0-9]+$/;

function resolveConvDir(conversationId: string): string | null {
  if (!CONV_ID_RE.test(conversationId)) return null;
  const dir = path.join(LOG_ROOT, conversationId);
  if (!dir.startsWith(LOG_ROOT + path.sep)) return null; // defense in depth
  return dir;
}

function mdPath(dir: string) {
  return path.join(dir, "questions-and-answers.md");
}
function jsonlPath(dir: string) {
  return path.join(dir, "session.jsonl");
}

export async function POST(request: NextRequest) {
  let body: { conversationId?: unknown; department?: unknown; turn?: unknown };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ message: "Malformed JSON body." }, { status: 400 });
  }
  const conversationId = typeof body.conversationId === "string" ? body.conversationId : "";
  const dir = resolveConvDir(conversationId);
  if (!dir) return NextResponse.json({ message: "Invalid or missing conversationId." }, { status: 400 });
  const department = typeof body.department === "string" ? body.department : "";
  const turn = body.turn as RawTurnInput | undefined;
  if (!turn || typeof turn.turnNumber !== "number") {
    return NextResponse.json({ message: "Missing turn record." }, { status: 400 });
  }

  try {
    await fs.mkdir(dir, { recursive: true });
    const md = mdPath(dir);
    // First write for this conversation: prepend the session header. A
    // logging failure here (disk full, permissions) must never fail the
    // chat turn itself - the caller (session-log.ts) already swallows this
    // route's own errors, so we only need to not throw the whole process.
    let exists = true;
    try {
      await fs.access(md);
    } catch {
      exists = false;
    }
    if (!exists) {
      await fs.writeFile(md, renderSessionHeader(conversationId, department, Date.now()));
    }
    await fs.appendFile(md, renderTurnMarkdown(turn));
    // The technical companion log: one raw JSON record per turn, exactly as
    // received - preserved alongside the human-readable file per turn, never
    // rewritten, so it can always regenerate or audit the .md above.
    await fs.appendFile(jsonlPath(dir), JSON.stringify({ department, ...turn }) + "\n");
  } catch (err) {
    // Never surface a 500 that could make a caller think the chat turn
    // itself failed - the turn already succeeded before this route ran.
    return NextResponse.json({ message: `Log write failed: ${(err as Error).message}` }, { status: 200 });
  }

  return NextResponse.json({ ok: true });
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

async function readLog(dir: string): Promise<string> {
  try {
    return await fs.readFile(mdPath(dir), "utf-8");
  } catch {
    return "_No turns logged yet for this conversation._\n";
  }
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const conversationId = searchParams.get("conversationId") ?? "";
  const mode = searchParams.get("mode") ?? "raw";
  const dir = resolveConvDir(conversationId);
  if (!dir) return NextResponse.json({ message: "Invalid or missing conversationId." }, { status: 400 });

  if (mode === "download") {
    const content = await readLog(dir);
    return new NextResponse(content, {
      headers: {
        "Content-Type": "text/markdown; charset=utf-8",
        "Content-Disposition": `attachment; filename="dejaq-session-${conversationId}.md"`,
      },
    });
  }

  if (mode === "raw") {
    const content = await readLog(dir);
    return new NextResponse(content, { headers: { "Content-Type": "text/plain; charset=utf-8" } });
  }

  // mode=view: a small self-contained page that polls the raw content and
  // re-renders it as it grows, so "updates as completed answers arrive"
  // holds without any push mechanism. Content is assigned via textContent
  // only (never innerHTML/dangerouslySetInnerHTML), so arbitrary user text
  // in the log can never execute as HTML here.
  const title = `DejaQ session log — ${escapeHtml(conversationId)}`;
  const html = `<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>${title}</title>
<style>
  body { font: 14px/1.5 -apple-system, system-ui, sans-serif; margin: 0; background: #0e0e10; color: #e8e8ea; }
  header { position: sticky; top: 0; background: #17171a; border-bottom: 1px solid #2a2a2e; padding: 10px 20px; display: flex; align-items: center; gap: 12px; }
  header h1 { font-size: 14px; font-weight: 600; margin: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  header a { color: #8ab4ff; text-decoration: none; font-size: 13px; }
  header span { font-size: 12px; color: #8a8a90; }
  pre { white-space: pre-wrap; word-break: break-word; padding: 20px; margin: 0; max-width: 900px; }
</style>
</head>
<body>
<header>
  <h1>${title}</h1>
  <span id="status">loading…</span>
  <a href="/api/session-log?conversationId=${encodeURIComponent(conversationId)}&mode=download">Download log</a>
</header>
<pre id="log">Loading…</pre>
<script>
  var convId = ${JSON.stringify(conversationId)};
  var el = document.getElementById("log");
  var statusEl = document.getElementById("status");
  async function refresh() {
    try {
      var res = await fetch("/api/session-log?conversationId=" + encodeURIComponent(convId) + "&mode=raw");
      var text = await res.text();
      if (el.textContent !== text) el.textContent = text;
      statusEl.textContent = "updated " + new Date().toLocaleTimeString();
    } catch (e) {
      statusEl.textContent = "connection lost, retrying…";
    }
  }
  refresh();
  setInterval(refresh, 2000);
</script>
</body>
</html>`;
  return new NextResponse(html, { headers: { "Content-Type": "text/html; charset=utf-8" } });
}
