import "server-only";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

/** Read-only client (anon/publishable key; RLS limits it to SELECT on public data). */
export function supabase(): SupabaseClient {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_ANON_KEY;
  if (!url || !key) throw new Error("SUPABASE_URL and SUPABASE_ANON_KEY must be set");
  return createClient(url, key, { auth: { persistSession: false } });
}
