interface TopbarProps {
  section: string;
  orgId?: string;
  extra?: React.ReactNode;
}

export default function Topbar({ section, orgId, extra }: TopbarProps) {
  return (
    <div className="ds-topbar">
      <div className="ds-breadcrumbs">
        {orgId && (
          <>
            <span className="ds-dimmer" style={{ fontFamily: "var(--font-mono)", fontSize: "11px" }}>{orgId}</span>
            <span className="sep">/</span>
          </>
        )}
        <span className="current">{section}</span>
      </div>

      <div className="ds-topbar-right">
        {extra}
        <div className="ds-env-pill">
          <span className="ds-status-dot" />
          all systems operational
        </div>
        <div className="ds-env-pill">local</div>
      </div>
    </div>
  );
}
