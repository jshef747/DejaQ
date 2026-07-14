import Link from "next/link";

export default function NotFound() {
  return (
    <div
      style={{
        minHeight: "100vh",
        background: "var(--bg)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        flexDirection: "column",
        gap: "16px",
        textAlign: "center",
        padding: "24px",
      }}
    >
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: "11px",
          color: "var(--fg-dimmer)",
          background: "var(--bg-2)",
          padding: "3px 8px",
          borderRadius: "4px",
          border: "1px solid var(--border)",
        }}
      >
        404
      </span>
      <h1
        style={{
          fontSize: "20px",
          fontWeight: 600,
          letterSpacing: "-0.02em",
          margin: 0,
          color: "var(--fg)",
        }}
      >
        Page not found
      </h1>
      <p style={{ margin: 0, color: "var(--fg-dim)", fontSize: "13px" }}>
        The page you&apos;re looking for doesn&apos;t exist.
      </p>
      <Link
        href="/dashboard"
        style={{
          fontSize: "12px",
          color: "var(--accent)",
          textDecoration: "none",
          fontFamily: "var(--font-mono)",
        }}
      >
        ← Back to dashboard
      </Link>
    </div>
  );
}
