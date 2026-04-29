"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { signOut } from "@/app/actions/auth";
import { listOrgs } from "@/app/actions/orgs";
import type { OrgItem } from "@/lib/types";

const NAV_ITEMS = [
  { href: "/dashboard/organizations", label: "Organizations", icon: OrgIcon },
  { href: "/dashboard/departments", label: "Departments", icon: DeptIcon },
  { href: "/dashboard/keys", label: "API Keys", icon: KeyIcon },
  { href: "/dashboard/analytics", label: "Analytics", icon: ChartIcon },
  { href: "/dashboard/settings", label: "Settings", icon: SettingsIcon },
];

// Pages that don't use ?org= — nav links go bare
const ORG_SCOPED_PATHS = ["/dashboard/departments", "/dashboard/keys", "/dashboard/organizations", "/dashboard/settings"];

interface SidebarProps {
  email: string;
}

export default function Sidebar({ email }: SidebarProps) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();
  const activeOrg = searchParams.get("org") ?? "";

  const [orgs, setOrgs] = useState<OrgItem[]>([]);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listOrgs().then(setOrgs).catch(() => {});
  }, []);

  // Auto-select first org if we're on an org-scoped page with no ?org=
  useEffect(() => {
    if (!activeOrg && orgs.length > 0) {
      const isScoped = ORG_SCOPED_PATHS.some((p) => pathname.startsWith(p));
      if (isScoped) {
        router.replace(`${pathname}?org=${orgs[0].slug}`);
      }
    }
  }, [activeOrg, orgs, pathname, router]);

  // Close dropdown on outside click
  useEffect(() => {
    if (!dropdownOpen) return;
    function handleClick(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [dropdownOpen]);

  function buildHref(base: string) {
    const isScoped = ORG_SCOPED_PATHS.some((p) => base.startsWith(p));
    return isScoped && activeOrg ? `${base}?org=${activeOrg}` : base;
  }

  function switchOrg(slug: string) {
    setDropdownOpen(false);
    const isScoped = ORG_SCOPED_PATHS.some((p) => pathname.startsWith(p));
    const target = isScoped ? `${pathname}?org=${slug}` : `/dashboard/departments?org=${slug}`;
    router.push(target);
  }

  const displayOrg = orgs.find((o) => o.slug === activeOrg) ?? orgs[0];
  const initials = email.slice(0, 2).toUpperCase();

  return (
    <aside
      style={{
        background: "#181818",
        borderRight: "1px solid var(--border)",
        display: "flex",
        flexDirection: "column",
        padding: "14px 10px",
        gap: "2px",
        position: "sticky",
        top: 0,
        height: "100vh",
        width: "220px",
        flexShrink: 0,
      }}
    >
      {/* Logo */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "8px",
          padding: "6px 8px 14px",
          borderBottom: "1px solid var(--border)",
          marginBottom: "10px",
        }}
      >
        <div
          style={{
            width: "22px",
            height: "22px",
            background: "var(--accent)",
            color: "#0a0a0a",
            fontFamily: "var(--font-mono)",
            fontWeight: 700,
            display: "grid",
            placeItems: "center",
            borderRadius: "4px",
            fontSize: "11px",
            letterSpacing: "-1px",
            flexShrink: 0,
          }}
        >
          Dq
        </div>
        <span style={{ fontWeight: 600, fontSize: "14px", letterSpacing: "-0.02em" }}>
          DejaQ
        </span>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: "10px",
            color: "var(--fg-dimmer)",
            marginLeft: "auto",
            padding: "2px 6px",
            border: "1px solid var(--border)",
            borderRadius: "3px",
          }}
        >
          v0
        </span>
      </div>

      {/* Org switcher */}
      <div ref={dropdownRef} style={{ position: "relative", marginBottom: "10px" }}>
        <button
          onClick={() => orgs.length > 1 && setDropdownOpen((v) => !v)}
          style={{
            alignItems: "center",
            background: "var(--bg-2)",
            border: "1px solid var(--border)",
            borderRadius: "5px",
            color: "var(--fg)",
            cursor: orgs.length > 1 ? "pointer" : "default",
            display: "flex",
            gap: "8px",
            padding: "7px 8px",
            textAlign: "left",
            width: "100%",
          }}
          onMouseEnter={(e) => {
            if (orgs.length > 1)
              (e.currentTarget as HTMLButtonElement).style.background = "var(--bg-3)";
          }}
          onMouseLeave={(e) =>
            ((e.currentTarget as HTMLButtonElement).style.background = "var(--bg-2)")
          }
        >
          <span
            style={{
              background: "var(--accent-bg)",
              border: "1px solid var(--accent-border)",
              borderRadius: "3px",
              color: "var(--accent)",
              display: "grid",
              flexShrink: 0,
              fontFamily: "var(--font-mono)",
              fontSize: "9px",
              fontWeight: 700,
              height: "14px",
              placeItems: "center",
              width: "14px",
            }}
          >
            {displayOrg?.name?.[0]?.toUpperCase() ?? "?"}
          </span>
          <span
            style={{
              flex: 1,
              fontSize: "12px",
              fontWeight: 500,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {displayOrg?.name ?? "Select org"}
          </span>
          {orgs.length > 1 && <ChevIcon />}
        </button>

        {dropdownOpen && (
          <div
            style={{
              background: "var(--bg-2)",
              border: "1px solid var(--border-2)",
              borderRadius: "5px",
              boxShadow: "0 4px 16px rgba(0,0,0,0.4)",
              left: 0,
              overflow: "hidden",
              position: "absolute",
              right: 0,
              top: "calc(100% + 4px)",
              zIndex: 20,
            }}
          >
            {orgs.map((org) => (
              <button
                key={org.slug}
                onClick={() => switchOrg(org.slug)}
                style={{
                  alignItems: "center",
                  background: org.slug === activeOrg ? "var(--bg-3)" : "transparent",
                  border: "none",
                  color: org.slug === activeOrg ? "var(--fg)" : "var(--fg-dim)",
                  cursor: "pointer",
                  display: "flex",
                  fontSize: "12px",
                  gap: "8px",
                  padding: "8px 10px",
                  textAlign: "left",
                  width: "100%",
                }}
                onMouseEnter={(e) =>
                  ((e.currentTarget as HTMLButtonElement).style.background = "var(--bg-3)")
                }
                onMouseLeave={(e) =>
                  ((e.currentTarget as HTMLButtonElement).style.background =
                    org.slug === activeOrg ? "var(--bg-3)" : "transparent")
                }
              >
                <span
                  style={{
                    background: "var(--accent-bg)",
                    border: "1px solid var(--accent-border)",
                    borderRadius: "3px",
                    color: "var(--accent)",
                    display: "grid",
                    flexShrink: 0,
                    fontFamily: "var(--font-mono)",
                    fontSize: "9px",
                    fontWeight: 700,
                    height: "14px",
                    placeItems: "center",
                    width: "14px",
                  }}
                >
                  {org.name[0].toUpperCase()}
                </span>
                <span
                  style={{
                    flex: 1,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {org.name}
                </span>
                {org.slug === activeOrg && (
                  <span style={{ color: "var(--accent)", fontSize: "11px" }}>✓</span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Nav section label */}
      <div
        style={{
          fontSize: "10px",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          color: "var(--fg-dimmer)",
          padding: "10px 8px 4px",
          fontWeight: 500,
        }}
      >
        Workspace
      </div>

      {/* Nav items */}
      {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
        const isActive = pathname === href || (href !== "/dashboard" && pathname.startsWith(href));
        return (
          <Link
            key={href}
            href={buildHref(href)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "10px",
              padding: "6px 8px",
              borderRadius: "5px",
              color: isActive ? "var(--fg)" : "var(--fg-dim)",
              background: isActive ? "var(--bg-3)" : "transparent",
              fontSize: "13px",
              textDecoration: "none",
              fontWeight: 400,
              transition: "background 0.1s, color 0.1s",
            }}
            onMouseEnter={(e) => {
              if (!isActive) {
                (e.currentTarget as HTMLAnchorElement).style.background = "var(--bg-3)";
                (e.currentTarget as HTMLAnchorElement).style.color = "var(--fg)";
              }
            }}
            onMouseLeave={(e) => {
              if (!isActive) {
                (e.currentTarget as HTMLAnchorElement).style.background = "transparent";
                (e.currentTarget as HTMLAnchorElement).style.color = "var(--fg-dim)";
              }
            }}
          >
            <Icon
              size={14}
              style={{ color: isActive ? "var(--accent)" : undefined, flexShrink: 0 }}
            />
            {label}
          </Link>
        );
      })}

      {/* Spacer */}
      <div style={{ flex: 1 }} />

      {/* Sidebar footer */}
      <div
        style={{
          paddingTop: "10px",
          borderTop: "1px solid var(--border)",
          display: "flex",
          alignItems: "center",
          gap: "8px",
          padding: "10px 8px 0",
        }}
      >
        <div
          style={{
            width: "22px",
            height: "22px",
            borderRadius: "50%",
            background: "linear-gradient(135deg, #555, #333)",
            fontSize: "10px",
            display: "grid",
            placeItems: "center",
            fontWeight: 600,
            color: "var(--fg)",
            flexShrink: 0,
          }}
        >
          {initials}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontSize: "12px",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {email}
          </div>
          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: "10px",
              color: "var(--fg-dimmer)",
            }}
          >
            owner
          </div>
        </div>
        <form action={signOut}>
          <button
            type="submit"
            title="Sign out"
            style={{
              background: "var(--bg-2)",
              border: "1px solid var(--border-2)",
              borderRadius: "4px",
              color: "var(--fg-dim)",
              padding: "3px 6px",
              fontSize: "11px",
              cursor: "pointer",
            }}
          >
            ↩
          </button>
        </form>
      </div>
    </aside>
  );
}

// Icons — inline SVGs at 14×14
function OrgIcon({ size = 14, style }: { size?: number; style?: React.CSSProperties }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" style={style}>
      <rect x="1" y="5" width="14" height="10" rx="1.5" />
      <path d="M5 5V3.5A1.5 1.5 0 0 1 6.5 2h3A1.5 1.5 0 0 1 11 3.5V5" />
    </svg>
  );
}

function DeptIcon({ size = 14, style }: { size?: number; style?: React.CSSProperties }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" style={style}>
      <circle cx="5" cy="6" r="2" />
      <circle cx="11" cy="6" r="2" />
      <path d="M1 14c0-2.2 1.8-4 4-4s4 1.8 4 4" />
      <path d="M11 10c1.4.4 3 1.6 3 4" />
    </svg>
  );
}

function KeyIcon({ size = 14, style }: { size?: number; style?: React.CSSProperties }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" style={style}>
      <circle cx="5.5" cy="8" r="3.5" />
      <path d="M9 8h6M13 8v2" />
    </svg>
  );
}

function ChartIcon({ size = 14, style }: { size?: number; style?: React.CSSProperties }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" style={style}>
      <path d="M1 12l4-4 3 3 4-5 3 3" />
    </svg>
  );
}

function SettingsIcon({ size = 14, style }: { size?: number; style?: React.CSSProperties }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" style={style}>
      <circle cx="8" cy="8" r="2.5" />
      <path d="M8 1v1.5M8 13.5V15M1 8h1.5M13.5 8H15M3.05 3.05l1.06 1.06M11.89 11.89l1.06 1.06M3.05 12.95l1.06-1.06M11.89 4.11l1.06-1.06" />
    </svg>
  );
}

function ChevIcon() {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5" style={{ color: "var(--fg-dimmer)" }}>
      <path d="M3 4l2 2 2-2" />
    </svg>
  );
}
