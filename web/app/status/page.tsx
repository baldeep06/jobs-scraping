import { StatusView } from "@/components/StatusView";
import { type RunRow, workflowHealth } from "@/lib/health";
import { REGION_COUNTRIES } from "@/lib/jobs";
import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

const TIERS = ["hot", "warm", "cold", "inactive"] as const;
const DAY_MS = 86_400_000;

export default async function StatusPage() {
  const client = supabase();
  const now = new Date();
  const since = new Date(now.getTime() - DAY_MS).toISOString();

  const [runs, jobsUs, jobsCa, ...tiers] = await Promise.all([
    client
      .from("scrape_runs")
      .select("workflow,finished_at,errors,companies_polled")
      .gte("finished_at", since)
      .order("finished_at", { ascending: false })
      .limit(400),
    client.from("jobs_feed").select("id", { count: "exact", head: true }).in("country", REGION_COUNTRIES.us),
    client.from("jobs_feed").select("id", { count: "exact", head: true }).in("country", REGION_COUNTRIES.ca),
    ...TIERS.map((t) =>
      client.from("companies").select("id", { count: "exact", head: true }).eq("tier", t),
    ),
  ]);
  const failed = [runs, jobsUs, jobsCa, ...tiers].find((r) => r.error);
  if (failed?.error) throw new Error(failed.error.message);

  return (
    <StatusView
      health={workflowHealth((runs.data ?? []) as RunRow[], now)}
      companiesByTier={Object.fromEntries(TIERS.map((t, i) => [t, tiers[i].count ?? 0]))}
      openJobs={{ us: jobsUs.count ?? 0, ca: jobsCa.count ?? 0 }}
    />
  );
}
