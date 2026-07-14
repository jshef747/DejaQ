type PillVariant = "hit" | "miss" | "err" | "neutral" | "blue" | "purple" | "green" | "amber";

interface PillProps {
  variant?: PillVariant;
  dot?: boolean;
  children: React.ReactNode;
  className?: string;
}

const VARIANT_CLASS: Record<PillVariant, string> = {
  hit:     "ds-pill-hit",
  miss:    "ds-pill-miss",
  err:     "ds-pill-err",
  neutral: "ds-pill-neutral",
  blue:    "ds-pill-blue",
  purple:  "ds-pill-purple",
  green:   "ds-pill-green",
  amber:   "ds-pill-amber",
};

export default function Pill({ variant = "neutral", dot, children, className = "" }: PillProps) {
  return (
    <span className={`ds-pill ${VARIANT_CLASS[variant]} ${className}`.trim()}>
      {dot && <span className="ds-pill-dot" />}
      {children}
    </span>
  );
}
