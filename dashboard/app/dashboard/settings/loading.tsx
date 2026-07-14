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

export default function SettingsLoading() {
  return (
    <>
      <Topbar section="Settings" />
      <div style={{ flex: 1, maxWidth: "900px", padding: "24px 28px" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginBottom: "24px" }}>
          <SkeletonBar width="110px" />
          <SkeletonBar width="320px" />
        </div>
        {Array.from({ length: 3 }).map((_, index) => (
          <div key={index} style={{ marginBottom: "28px" }}>
            <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginBottom: "10px" }}>
              <SkeletonBar width="160px" />
              <SkeletonBar width="440px" />
            </div>
            <div
              style={{
                animation: "skeleton-pulse 1.4s ease-in-out infinite",
                background: "var(--bg-2)",
                border: "1px solid var(--border)",
                borderRadius: "6px",
                height: index === 0 ? "310px" : "150px",
              }}
            />
          </div>
        ))}
      </div>
    </>
  );
}
