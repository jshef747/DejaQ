"use client";

import { forwardRef } from "react";
import type { LucideIcon } from "lucide-react";

interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  icon: LucideIcon;
  label: string; // required for a11y
  size?: number;
  variant?: "default" | "ghost" | "danger";
}

const VARIANT_CLASS = {
  default: "ds-btn ds-btn-icon",
  ghost:   "ds-btn ds-btn-ghost ds-btn-icon",
  danger:  "ds-btn ds-btn-ghost-danger ds-btn-icon",
};

const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  ({ icon: Icon, label, size = 14, variant = "default", className = "", ...props }, ref) => {
    return (
      <button
        ref={ref}
        aria-label={label}
        title={label}
        className={`${VARIANT_CLASS[variant]} ${className}`.trim()}
        {...props}
      >
        <Icon size={size} />
      </button>
    );
  }
);
IconButton.displayName = "IconButton";
export default IconButton;
