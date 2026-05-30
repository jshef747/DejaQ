"use server";

import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { isLocalAuth } from "@/lib/authMode";

export async function signIn(formData: FormData) {
  // Local dev bypass: no Supabase — there is no login.
  if (isLocalAuth) redirect("/dashboard");

  const supabase = await createClient();
  const email = formData.get("email") as string;
  const password = formData.get("password") as string;

  const { error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) return { error: error.message };

  redirect("/dashboard");
}

export async function signUp(formData: FormData) {
  if (isLocalAuth) redirect("/dashboard");

  const supabase = await createClient();
  const email = formData.get("email") as string;
  const password = formData.get("password") as string;

  const { error } = await supabase.auth.signUp({ email, password });
  if (error) return { error: error.message };

  redirect("/dashboard");
}

export async function signOut() {
  // No session to clear in local mode.
  if (isLocalAuth) redirect("/dashboard");

  const supabase = await createClient();
  await supabase.auth.signOut();
  redirect("/login");
}
