interface TopbarProps {
  section: string;
  orgId?: string;
  sub?: string;
}

export default function Topbar({ section, orgId, sub }: TopbarProps) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        padding: "0 24px",
        height: "48px",
        borderBottom: "1px solid var(--border)",
        gap: "12px",
        background: "var(--bg)",
        flexShrink: 0,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "8px",
          fontSize: "12px",
          color: "var(--fg-dim)",
          fontFamily: "var(--font-mono)",
        }}
      >
        {orgId && (
          <>
            <span style={{ color: "var(--fg-dimmer)" }}>{orgId}</span>
            <span style={{ color: "var(--fg-dimmer)" }}>/</span>
          </>
        )}
        {sub ? (
          <>
            <span>{section}</span>
            <span style={{ color: "var(--fg-dimmer)" }}>/</span>
            <span style={{ color: "var(--fg)" }}>{sub}</span>
          </>
        ) : (
          <span style={{ color: "var(--fg)" }}>{section}</span>
        )}
      </div>

      <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "8px" }}>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: "11px",
            padding: "3px 8px",
            border: "1px solid var(--border)",
            borderRadius: "4px",
            color: "var(--fg-dim)",
            background: "var(--bg-2)",
            display: "flex",
            alignItems: "center",
            gap: "6px",
          }}
        >
          <span
            style={{
              width: "6px",
              height: "6px",
              borderRadius: "50%",
              background: "var(--green)",
              boxShadow: "0 0 6px var(--green)",
              display: "inline-block",
              flexShrink: 0,
            }}
          />
          all systems operational
        </div>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: "11px",
            padding: "3px 8px",
            border: "1px solid var(--border)",
            borderRadius: "4px",
            color: "var(--fg-dim)",
            background: "var(--bg-2)",
          }}
        >
          local
        </div>
      </div>
    </div>
  );
}
