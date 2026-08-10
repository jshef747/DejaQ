import Topbar from "@/components/Topbar";

function SkeletonBar({ width = "60%" }: { width?: string }) {
  return (
    <div
      style={{
        animation: "skeleton-pulse 1.4s ease-in-out infinite",
        background: "var(--bg-3)",
        borderRadius: "3px",
        height: "10px",
        width,
      }}
    />
  );
}

export default function PipelineLoading() {
  return (
    <>
      <Topbar section="Pipeline" />
      <div style={{ flex: 1, padding: "24px 28px" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginBottom: "24px" }}>
          <SkeletonBar width="90px" />
          <SkeletonBar width="420px" />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: "10px", alignItems: "center" }}>
          {Array.from({ length: 5 }).map((_, index) => (
            <div
              key={index}
              style={{
                animation: "skeleton-pulse 1.4s ease-in-out infinite",
                background: "var(--bg-2)",
                border: "1px solid var(--border)",
                borderRadius: "9px",
                height: "56px",
                width: "100%",
                maxWidth: "430px",
              }}
            />
          ))}
        </div>
      </div>
    </>
  );
}
