interface CardProps {
  title?: string;
  subtitle?: string;
  headerRight?: React.ReactNode;
  children: React.ReactNode;
  danger?: boolean;
  className?: string;
  noPadding?: boolean;
}

export default function Card({ title, subtitle, headerRight, children, danger, className = "", noPadding }: CardProps) {
  return (
    <div className={`ds-card ${danger ? "ds-danger-card" : ""} ${className}`.trim()}>
      {title && (
        <div className="ds-card-header">
          <div>
            <p className="ds-card-title">{title}</p>
            {subtitle && <p className="ds-card-sub">{subtitle}</p>}
          </div>
          {headerRight}
        </div>
      )}
      {noPadding ? children : <div className="ds-card-body">{children}</div>}
    </div>
  );
}
