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

export default function OrganizationsLoading() {
  return (
    <>
      <Topbar section="Organizations" />
      <div style={{ padding: "24px 28px", flex: 1 }}>
        <div style={{ marginBottom: "20px" }}>
          <div style={{ marginBottom: "8px" }}>
            <SkeletonBar width="140px" />
          </div>
          <SkeletonBar width="220px" />
        </div>
        <div style={{ border: "1px solid var(--border)", borderRadius: "6px", overflow: "hidden" }}>
          <div
            style={{
              background: "var(--bg-2)",
              borderBottom: "1px solid var(--border)",
              padding: "8px 14px",
            }}
          >
            <SkeletonBar width="100%" />
          </div>
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              style={{
                borderBottom: "1px solid var(--border)",
                display: "grid",
                gap: "14px",
                gridTemplateColumns: "2fr 1.5fr 1.5fr 0.5fr",
                padding: "12px 14px",
              }}
            >
              <SkeletonBar width="70%" />
              <SkeletonBar width="55%" />
              <SkeletonBar width="65%" />
              <SkeletonBar width="30px" />
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
