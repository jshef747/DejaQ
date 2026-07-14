function SkeletonBar({ w = "100%", h = 12 }: { w?: string | number; h?: number }) {
  return (
    <div
      style={{
        width: w,
        height: h,
        background: "var(--bg-3)",
        borderRadius: 3,
        animation: "skeleton-pulse 1.4s ease-in-out infinite",
      }}
    />
  );
}

export default function AnalyticsLoading() {
  return (
    <>
      {/* Topbar placeholder */}
      <div
        style={{
          height: 48,
          borderBottom: "1px solid var(--border)",
          background: "var(--bg)",
          flexShrink: 0,
        }}
      />
      <div style={{ padding: "24px 28px", flex: 1 }}>
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 20 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <SkeletonBar w={140} h={22} />
            <SkeletonBar w={280} h={13} />
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <SkeletonBar w={80} h={32} />
            <SkeletonBar w={72} h={32} />
            <SkeletonBar w={88} h={32} />
          </div>
        </div>

        {/* Metric cards */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(4, 1fr)",
            gap: 12,
            marginBottom: 20,
          }}
        >
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              style={{
                background: "var(--bg-2)",
                border: "1px solid var(--border)",
                borderRadius: 6,
                padding: "14px 16px",
                display: "flex",
                flexDirection: "column",
                gap: 10,
              }}
            >
              <SkeletonBar w={80} h={11} />
              <SkeletonBar w={100} h={26} />
              <SkeletonBar w={120} h={11} />
            </div>
          ))}
        </div>

        {/* Two-col: chart + routing */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "2fr 1fr",
            gap: 12,
            marginBottom: 20,
          }}
        >
          <div
            style={{
              background: "var(--bg-2)",
              border: "1px solid var(--border)",
              borderRadius: 6,
              overflow: "hidden",
            }}
          >
            <div
              style={{
                padding: "12px 16px",
                borderBottom: "1px solid var(--border)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <SkeletonBar w={160} h={13} />
              <div style={{ display: "flex", gap: 4 }}>
                {Array.from({ length: 3 }).map((_, i) => (
                  <SkeletonBar key={i} w={32} h={24} />
                ))}
              </div>
            </div>
            <div
              style={{
                padding: 16,
                height: 272,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <SkeletonBar w="100%" h={240} />
            </div>
          </div>
          <div
            style={{
              background: "var(--bg-2)",
              border: "1px solid var(--border)",
              borderRadius: 6,
              overflow: "hidden",
            }}
          >
            <div
              style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)" }}
            >
              <SkeletonBar w={120} h={13} />
            </div>
            <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 16 }}>
              {Array.from({ length: 2 }).map((_, i) => (
                <div key={i} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <SkeletonBar w={80} h={12} />
                    <SkeletonBar w={36} h={12} />
                  </div>
                  <SkeletonBar w="100%" h={4} />
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Table */}
        <div
          style={{
            background: "var(--bg-2)",
            border: "1px solid var(--border)",
            borderRadius: 6,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              padding: "12px 16px",
              borderBottom: "1px solid var(--border)",
              display: "flex",
              justifyContent: "space-between",
            }}
          >
            <SkeletonBar w={160} h={13} />
            <SkeletonBar w={48} h={24} />
          </div>
          {/* Header row */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 180px 100px 100px 100px 160px",
              gap: 12,
              padding: "9px 12px",
              background: "#1d1d1d",
              borderBottom: "1px solid var(--border)",
            }}
          >
            {Array.from({ length: 6 }).map((_, i) => (
              <SkeletonBar key={i} w="60%" h={10} />
            ))}
          </div>
          {/* Body rows */}
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 180px 100px 100px 100px 160px",
                gap: 12,
                padding: "10px 12px",
                borderBottom: i < 3 ? "1px solid var(--border)" : "none",
              }}
            >
              <SkeletonBar w="55%" h={12} />
              <SkeletonBar w="70%" h={12} />
              <SkeletonBar w="50%" h={12} />
              <SkeletonBar w="50%" h={12} />
              <SkeletonBar w="50%" h={12} />
              <SkeletonBar w="65%" h={12} />
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
