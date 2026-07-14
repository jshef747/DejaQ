export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { isLocalAuth } from "@/lib/authMode";
import Sidebar from "@/components/Sidebar";

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
