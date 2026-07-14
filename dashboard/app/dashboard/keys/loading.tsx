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

export default function KeysLoading() {
  return (
    <>
      <Topbar section="API Keys" />
      <div style={{ padding: "24px 28px", flex: 1 }}>
        <div
          style={{
            alignItems: "flex-start",
            display: "flex",
            justifyContent: "space-between",
            marginBottom: "20px",
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
            <SkeletonBar width="100px" />
            <SkeletonBar width="160px" />
          </div>
          <div
            style={{
              animation: "skeleton-pulse 1.4s ease-in-out infinite",
              background: "var(--bg-3)",
              borderRadius: "5px",
              height: "30px",
              width: "120px",
            }}
          />
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
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              style={{
                borderBottom: "1px solid var(--border)",
                display: "grid",
                gap: "14px",
                gridTemplateColumns: "2fr 1fr 0.7fr 40px",
                padding: "12px 14px",
              }}
            >
              <SkeletonBar width="85%" />
              <SkeletonBar width="60%" />
              <SkeletonBar width="50px" />
              <SkeletonBar width="20px" />
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
