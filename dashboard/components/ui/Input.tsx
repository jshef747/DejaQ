"use client";

import { forwardRef, useState } from "react";
import { Eye, EyeOff } from "lucide-react";

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  mono?: boolean;
  reveal?: boolean; // adds show/hide toggle for password fields
}

const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ mono, reveal, type, className = "", ...props }, ref) => {
    const [shown, setShown] = useState(false);

    const cls = `ds-input ${mono ? "ds-input-mono" : "ds-input-sans"} ${className}`.trim();

    if (reveal && type === "password") {
      return (
        <div className="ds-input-wrap">
          <input
            ref={ref}
            type={shown ? "text" : "password"}
            className={cls}
            {...props}
          />
          <button
            type="button"
            className="ds-input-reveal"
            aria-label={shown ? "Hide password" : "Show password"}
            onClick={() => setShown((v) => !v)}
          >
            {shown ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
        </div>
      );
    }

    return <input ref={ref} type={type} className={cls} {...props} />;
  }
);
Input.displayName = "Input";
export default Input;
