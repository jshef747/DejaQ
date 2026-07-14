interface SkeletonProps {
  variant?: "text" | "title" | "pill" | "row" | "block";
  width?: string | number;
  height?: string | number;
  className?: string;
  style?: React.CSSProperties;
}

const VARIANT_CLASS: Record<string, string> = {
  text:  "ds-skeleton ds-skeleton-text",
  title: "ds-skeleton ds-skeleton-title",
  pill:  "ds-skeleton ds-skeleton-pill",
  row:   "ds-skeleton ds-skeleton-row",
  block: "ds-skeleton",
};

export default function Skeleton({ variant = "text", width, height, className = "", style }: SkeletonProps) {
  return (
    <div
      className={`${VARIANT_CLASS[variant]} ${className}`.trim()}
      style={{ width, height, ...style }}
    />
  );
}

export function SkeletonRows({ count = 4 }: { count?: number }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
      {Array.from({ length: count }).map((_, i) => (
        <Skeleton key={i} variant="row" />
      ))}
    </div>
  );
}
