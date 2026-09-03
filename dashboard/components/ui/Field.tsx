import { cloneElement, isValidElement, useId } from "react";

interface FieldProps {
  label?: string;
  hint?: string;
  error?: string;
  required?: boolean;
  labelRight?: React.ReactNode;
  id?: string;
  children: React.ReactNode;
}

export default function Field({ label, hint, error, required, labelRight, id, children }: FieldProps) {
  const generatedId = useId();
  const fieldId = id ?? generatedId;

  // Only auto-wire an id onto a single-element child when the caller didn't
  // already take responsibility for wiring one (via an explicit `id` prop) -
  // otherwise a wrapper element (e.g. an input + a button) would get the same
  // id as the real control the caller wired it to, producing a DOM duplicate.
  const child =
    id === undefined && isValidElement<{ id?: string }>(children) && !children.props.id
      ? cloneElement(children, { id: fieldId })
      : children;

  return (
    <div className="ds-field">
      {label && (
        <div className="ds-field-label-row">
          <label htmlFor={fieldId} className="ds-field-label">
            {label}
            {required && <span style={{ color: "var(--red)", marginLeft: 2 }}>*</span>}
          </label>
          {labelRight}
        </div>
      )}
      {child}
      {hint && !error && <div className="ds-field-hint">{hint}</div>}
      {error && <div className="ds-field-error">{error}</div>}
    </div>
  );
}
