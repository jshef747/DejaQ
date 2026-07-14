"use client";

import { forwardRef } from "react";
import { Loader2 } from "lucide-react";

type Variant = "default" | "primary" | "danger" | "ghost" | "ghost-danger";
type Size = "sm" | "md";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

const VARIANT_CLASS: Record<Variant, string> = {
  default:      "ds-btn",
  primary:      "ds-btn ds-btn-primary",
  danger:       "ds-btn ds-btn-danger",
  ghost:        "ds-btn ds-btn-ghost",
  "ghost-danger": "ds-btn ds-btn-ghost-danger",
};

const SIZE_CLASS: Record<Size, string> = {
  sm: "ds-btn-sm",
  md: "",
};

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "default", size = "md", loading, disabled, children, className = "", ...props }, ref) => {
    return (
      <button
        ref={ref}
        disabled={disabled || loading}
        className={`${VARIANT_CLASS[variant]} ${SIZE_CLASS[size]} ${className}`.trim()}
        {...props}
      >
        {loading && <Loader2 size={12} style={{ animation: "spin 1s linear infinite" }} />}
        {children}
      </button>
    );
  }
);
Button.displayName = "Button";
export default Button;
