interface FieldProps {
  label?: string;
  hint?: string;
  error?: string;
  required?: boolean;
  labelRight?: React.ReactNode;
  children: React.ReactNode;
}

export default function Field({ label, hint, error, required, labelRight, children }: FieldProps) {
  return (
    <div className="ds-field">
      {label && (
        <div className="ds-field-label-row">
          <span className="ds-field-label">
            {label}
            {required && <span style={{ color: "var(--red)", marginLeft: 2 }}>*</span>}
          </span>
          {labelRight}
        </div>
      )}
      {children}
      {hint && !error && <div className="ds-field-hint">{hint}</div>}
      {error && <div className="ds-field-error">{error}</div>}
    </div>
  );
}
