import { redirect } from "next/navigation";
import { isLocalAuth } from "@/lib/authMode";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  // Local dev bypass: no login screen — go straight to the dashboard.
  if (isLocalAuth) redirect("/dashboard");

  return (
    <div style={{ minHeight: "100dvh", background: "var(--bg)", color: "var(--fg)", display: "grid", gridTemplateColumns: "1fr 1fr" }}>
      {/* Left marketing panel */}
      <div style={{
        background: "linear-gradient(180deg, #181818 0%, #141414 100%)",
        borderRight: "1px solid var(--border)",
        padding: "40px 48px",
        display: "flex",
        flexDirection: "column",
        position: "relative",
        overflow: "hidden",
      }}>
        {/* Subtle grid pattern */}
        <div style={{
          position: "absolute", inset: 0, pointerEvents: "none",
          backgroundImage: "linear-gradient(var(--border) 1px, transparent 1px), linear-gradient(90deg, var(--border) 1px, transparent 1px)",
          backgroundSize: "28px 28px",
          opacity: 0.35,
          maskImage: "radial-gradient(circle at 60% 40%, black 0%, transparent 70%)",
        }} />

        <div style={{ display: "flex", alignItems: "center", gap: 10, position: "relative" }}>
          <div className="ds-logo-mark" style={{ width: 28, height: 28, fontSize: 15, fontFamily: "var(--font-mono)" }}>Dq</div>
          <div style={{ fontWeight: 600, fontSize: 16, letterSpacing: "-0.02em" }}>DejaQ</div>
        </div>

        <div style={{ marginTop: 64, position: "relative" }}>
          <div style={{ fontSize: 11, color: "var(--accent)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 14 }}>
            semantic cache · for llm apps
          </div>
          <h1 style={{ fontSize: 36, lineHeight: 1.15, letterSpacing: "-0.03em", fontWeight: 600, margin: 0, maxWidth: 440 }}>
            Stop paying twice<br />
            for the <span style={{ color: "var(--accent)" }}>same answer.</span>
          </h1>
          <p style={{ marginTop: 14, fontSize: 13, color: "var(--fg-dim)", maxWidth: 420, lineHeight: 1.6 }}>
            Route repetitive queries to a local cache, hard queries to frontier models.
            Ship faster, cut provider bills by up to 80%.
          </p>
        </div>

        {/* Live request feed */}
        <div style={{ marginTop: 40, position: "relative" }}>
          <div style={{ border: "1px solid var(--border)", borderRadius: 6, background: "var(--bg-2)", overflow: "hidden", maxWidth: 460 }}>
            <div style={{
              padding: "7px 12px", fontSize: 10.5, color: "var(--fg-dimmer)",
              borderBottom: "1px solid var(--border)",
              display: "flex", justifyContent: "space-between", alignItems: "center",
            }}>
              <span>live · customer-support</span>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <span style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--green)", boxShadow: "0 0 6px var(--green)" }} />
                streaming
              </span>
            </div>
            <div style={{ padding: "10px 12px", lineHeight: 1.9, fontSize: 11 }}>
              {[
                { t: "14:22:08", status: "HIT",  ms: 86,   q: "how do I rotate keys" },
                { t: "14:22:11", status: "HIT",  ms: 94,   q: "what plans are available" },
                { t: "14:22:14", status: "MISS", ms: 1820, q: "rate limits for bulk embed" },
                { t: "14:22:16", status: "HIT",  ms: 71,   q: "how to cancel my account" },
                { t: "14:22:19", status: "HIT",  ms: 88,   q: "what's the refund policy" },
                { t: "14:22:22", status: "HIT",  ms: 102,  q: "reset password email" },
              ].map((row, i) => (
                <div key={i} style={{
                  display: "grid", gridTemplateColumns: "60px 52px 1fr 54px", gap: 10, alignItems: "center",
                  opacity: 1 - i * 0.07,
                  fontFamily: "var(--font-mono)",
                }}>
                  <span style={{ color: "var(--fg-dimmer)" }}>{row.t}</span>
                  <span style={{ color: row.status === "HIT" ? "var(--accent)" : "var(--amber)", fontWeight: 600 }}>{row.status}</span>
                  <span style={{ color: "var(--fg-dim)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{row.q}</span>
                  <span style={{ color: row.status === "HIT" ? "var(--accent)" : "var(--fg-dim)", textAlign: "right" }}>{row.ms}ms</span>
                </div>
              ))}
            </div>
            <div style={{
              padding: "8px 12px", borderTop: "1px solid var(--border)",
              display: "flex", justifyContent: "space-between",
              fontSize: 10.5, fontFamily: "var(--font-mono)", color: "var(--fg-dimmer)",
            }}>
              <span>last 6 events · <span style={{ color: "var(--accent)" }}>5 hits</span> · <span style={{ color: "var(--amber)" }}>1 miss</span></span>
              <span>hit rate <span style={{ color: "var(--accent)" }}>83%</span></span>
            </div>
          </div>
        </div>

        <div style={{ marginTop: "auto", display: "flex", gap: 20, fontSize: 11, color: "var(--fg-dimmer)", fontFamily: "var(--font-mono)", position: "relative" }}>
          <span>self-hostable</span><span>·</span><span>80% cheaper bills</span>
        </div>
      </div>

      {/* Right — form */}
      <div style={{ display: "grid", placeItems: "center", padding: 40 }}>
        {children}
      </div>
    </div>
  );
}
