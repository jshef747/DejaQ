import type { LucideIcon } from "lucide-react";

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
}

export default function EmptyState({ icon: Icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="ds-empty">
      {Icon && <Icon size={32} className="ds-empty-icon" />}
      <p className="ds-empty-title">{title}</p>
      {description && <p className="ds-empty-sub">{description}</p>}
      {action}
    </div>
  );
}
