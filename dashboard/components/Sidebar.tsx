"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  BarChart2,
  Briefcase,
  Users,
  Key,
  Settings,
  MessageSquare,
  GitBranch,
  ChevronDown,
  Check,
  LogOut,
} from "lucide-react";
import { signOut } from "@/app/actions/auth";
import { listWorkspaces } from "@/app/actions/workspaces";
import type { WorkspaceItem } from "@/lib/types";

const CHAT_URL = process.env.NEXT_PUBLIC_CHAT_URL ?? "http://localhost:4000";

const NAV_ITEMS = [
  { href: "/dashboard/analytics",   label: "Analytics",   Icon: BarChart2 },
  { href: "/dashboard/workspaces",  label: "Workspaces",  Icon: Briefcase },
  { href: "/dashboard/departments", label: "Departments", Icon: Users },
  { href: "/dashboard/tree",        label: "Workspace Tree", Icon: GitBranch },
  { href: "/dashboard/keys",        label: "API Keys",    Icon: Key },
];

const WORKSPACE_SCOPED_PATHS = [
  "/dashboard/departments",
  "/dashboard/keys",
  "/dashboard/workspaces",
  "/dashboard/settings",
  "/dashboard/tree",
];

interface SidebarProps {
  email: string;
}

export default function Sidebar({ email }: SidebarProps) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();
  const activeWorkspace = searchParams.get("workspace") ?? "";

  const [workspaces, setWorkspaces] = useState<WorkspaceItem[]>([]);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listWorkspaces().then(setWorkspaces).catch(() => {});
  }, []);

  useEffect(() => {
    if (workspaces.length === 0) return;
    const isScoped = WORKSPACE_SCOPED_PATHS.some((p) => pathname.startsWith(p));
    if (!isScoped) return;
    const slugValid = workspaces.some((w) => w.slug === activeWorkspace);
    // Redirect when there is no workspace selected, or when the selected slug no longer exists.
    if (!activeWorkspace || !slugValid) {
      router.replace(`${pathname}?workspace=${workspaces[0].slug}`);
    }
  }, [activeWorkspace, workspaces, pathname, router]);

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
    const isScoped = WORKSPACE_SCOPED_PATHS.some((p) => base.startsWith(p));
    return isScoped && activeWorkspace ? `${base}?workspace=${activeWorkspace}` : base;
  }

  function switchWorkspace(slug: string) {
    setDropdownOpen(false);
    const isScoped = WORKSPACE_SCOPED_PATHS.some((p) => pathname.startsWith(p));
    const target = isScoped ? `${pathname}?workspace=${slug}` : `/dashboard/departments?workspace=${slug}`;
    router.push(target);
  }

  const displayWorkspace = workspaces.find((w) => w.slug === activeWorkspace) ?? workspaces[0];
  const initials = email.slice(0, 2).toUpperCase();

  return (
    <aside className="ds-sidebar" style={{ width: "220px", minWidth: 0 }}>
      {/* Logo */}
      <div className="ds-logo">
        <div className="ds-logo-mark" style={{ fontFamily: "var(--font-mono)" }}>Dq</div>
        <span className="ds-logo-text">DejaQ</span>
        <span className="ds-logo-badge">v0</span>
      </div>

      {/* Workspace switcher */}
      <div ref={dropdownRef} style={{ position: "relative", marginBottom: "10px" }}>
        <button
          className="ds-org-switcher"
          onClick={() => workspaces.length > 1 && setDropdownOpen((v) => !v)}
          style={{ cursor: workspaces.length > 1 ? "pointer" : "default" }}
        >
          <span className="ds-org-initials">
            {displayWorkspace?.name?.[0]?.toUpperCase() ?? "?"}
          </span>
          <span className="ds-org-name">{displayWorkspace?.name ?? "Select workspace"}</span>
          {workspaces.length > 1 && <ChevronDown size={12} style={{ color: "var(--fg-dimmer)", flexShrink: 0 }} />}
        </button>

        {dropdownOpen && (
          <div className="ds-org-dropdown">
            {workspaces.map((ws) => (
              <button
                key={ws.slug}
                onClick={() => switchWorkspace(ws.slug)}
                className={`ds-nav-item${ws.slug === activeWorkspace ? " active" : ""}`}
              >
                <span className="ds-org-initials">{ws.name[0].toUpperCase()}</span>
                <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {ws.name}
                </span>
                {ws.slug === activeWorkspace && <Check size={11} style={{ color: "var(--accent)", flexShrink: 0 }} />}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Nav */}
      <div className="ds-nav-section">Workspace</div>
      {NAV_ITEMS.map(({ href, label, Icon }) => {
        const isActive = pathname === href || (href !== "/dashboard" && pathname.startsWith(href));
        return (
          <Link
            key={href}
            href={buildHref(href)}
            className={`ds-nav-item${isActive ? " active" : ""}`}
            title={label}
            aria-label={label}
          >
            <Icon size={14} className="ds-nav-icon" />
            {label}
          </Link>
        );
      })}

      {/* Chat external link */}
      <a
        href={CHAT_URL}
        target="_blank"
        rel="noopener noreferrer"
        className="ds-nav-item"
        title="Chat demo"
        aria-label="Chat demo (opens in new tab)"
      >
        <MessageSquare size={14} className="ds-nav-icon" />
        Chat demo ↗
      </a>

      {/* Account section */}
      <div className="ds-nav-section">Account</div>
      <Link
        href={buildHref("/dashboard/settings")}
        className={`ds-nav-item${pathname.startsWith("/dashboard/settings") ? " active" : ""}`}
        title="Settings"
        aria-label="Settings"
      >
        <Settings size={14} className="ds-nav-icon" />
        Settings
      </Link>

      {/* Spacer */}
      <div style={{ flex: 1 }} />

      {/* Footer */}
      <div className="ds-sidebar-footer">
        <div className="ds-avatar">{initials}</div>
        <div className="ds-sidebar-user">
          <div className="ds-sidebar-user-name">{email}</div>
          <div className="ds-sidebar-user-role" style={{ fontFamily: "var(--font-mono)" }}>owner</div>
        </div>
        <form action={signOut}>
          <button
            type="submit"
            title="Sign out"
            aria-label="Sign out"
            className="ds-btn ds-btn-ghost ds-btn-icon"
          >
            <LogOut size={13} />
          </button>
        </form>
      </div>
    </aside>
  );
}
