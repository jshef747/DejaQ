interface SectionHeaderProps {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
}

export default function SectionHeader({ title, subtitle, action }: SectionHeaderProps) {
  return (
    <div className="ds-page-header">
      <div>
        <h1 className="ds-page-title">{title}</h1>
        {subtitle && <p className="ds-page-sub">{subtitle}</p>}
      </div>
      {action && <div style={{ display: "flex", gap: "8px", alignItems: "center", flexShrink: 0 }}>{action}</div>}
    </div>
  );
}
