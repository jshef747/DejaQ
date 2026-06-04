export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { isLocalAuth } from "@/lib/authMode";
import Sidebar from "@/components/Sidebar";
import { listWorkspaces } from "@/app/actions/workspaces";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  let email = "dev@localhost";
  if (!isLocalAuth) {
    const supabase = await createClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();

    if (!user) redirect("/login");
    email = user.email ?? "unknown";
  }

  // Onboarding guard: if no workspaces exist, send the user through first-run setup.
  // On backend error, fall through — the dashboard shows its own "unavailable" state.
  try {
    const workspaces = await listWorkspaces();
    if (workspaces.length === 0) {
      redirect("/onboarding");
    }
  } catch {
    // Backend unavailable — fall through to dashboard's error UI.
  }

  return (
    <div className="ds-app">
      <Suspense fallback={<aside className="ds-sidebar" style={{ width: "220px", minWidth: 0 }} />}>
        <Sidebar email={email} />
      </Suspense>
      <main className="ds-main">
        {children}
      </main>
    </div>
  );
}
