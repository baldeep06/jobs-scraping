import type { SupabaseClient } from "@supabase/supabase-js";
import { type Filters, PAGE_SIZE } from "@/lib/filters";
import type { Country, JobRow, JobSource, Region } from "@/lib/types";

export const REGION_COUNTRIES: Record<Region, Country[]> = {
  us: ["US", "BOTH", "UNKNOWN"],
  ca: ["CA", "BOTH", "UNKNOWN"],
};

const WITHIN_MS = { "1h": 3_600_000, "24h": 86_400_000, "7d": 604_800_000 } as const;

export interface FilterableQuery {
  in(column: string, values: readonly unknown[]): this;
  eq(column: string, value: unknown): this;
  ilike(column: string, pattern: string): this;
  gte(column: string, value: string): this;
  not(column: string, operator: string, value: unknown): this;
  or(filters: string): this;
  order(column: string, options: { ascending: boolean; nullsFirst?: boolean }): this;
  range(from: number, to: number): this;
}

export function applyFilters<Q extends FilterableQuery>(query: Q, f: Filters, now: Date): Q {
  let q = query.in("country", REGION_COUNTRIES[f.region]).in("visa_status", f.visa);
  if (f.category) q = q.eq("category", f.category);
  if (f.term) q = q.ilike("term", `%${f.term}%`);
  if (f.within !== "all") {
    q = q.gte("first_seen_at", new Date(now.getTime() - WITHIN_MS[f.within]).toISOString());
  }
  if (f.fresh) q = q.in("freshness", ["fresh", "recurring"]);
  if (f.pay) q = q.not("pay_hourly_max", "is", null);
  if (f.remote) q = q.eq("work_mode", "remote");
  if (f.q) {
    // f.q is sanitized by parseFilters (no quotes, commas, parens or %), so quoting is safe.
    q = q.or(`title.ilike."%${f.q}%",company_name.ilike."%${f.q}%"`);
  }
  if (f.sort === "pay") q = q.order("pay_hourly_max", { ascending: false, nullsFirst: false });
  q = q.order("first_seen_at", { ascending: false });
  const from = (f.page - 1) * PAGE_SIZE;
  return q.range(from, from + PAGE_SIZE - 1);
}

const COLUMNS =
  "id,title,company_name,company_domain,category,term,location_raw,locations,country," +
  "work_mode,location_unclear,pay_hourly_min,pay_hourly_max,pay_currency,pay_raw," +
  "visa_status,visa_signals,flags,evidence,freshness,repost_count,first_seen_at,best_url,h1b_count";

export async function fetchJobs(
  client: SupabaseClient,
  f: Filters,
  now: Date,
): Promise<{ rows: JobRow[]; total: number }> {
  const base = client.from("jobs_feed").select(COLUMNS, { count: "exact" });
  const filtered = applyFilters(base as unknown as FilterableQuery, f, now);
  const { data, count, error } = await (filtered as unknown as typeof base);
  if (error) throw new Error(`jobs query failed: ${error.message}`);
  return { rows: (data ?? []) as unknown as JobRow[], total: count ?? 0 };
}

export async function fetchSources(
  client: SupabaseClient,
  ids: string[],
): Promise<Record<string, JobSource[]>> {
  if (ids.length === 0) return {};
  const { data, error } = await client
    .from("job_sources")
    .select("job_id,source,url,first_seen_at")
    .in("job_id", ids)
    .order("first_seen_at", { ascending: true });
  if (error) throw new Error(`sources query failed: ${error.message}`);
  const out: Record<string, JobSource[]> = {};
  for (const s of (data ?? []) as JobSource[]) {
    out[s.job_id] ??= [];
    out[s.job_id].push(s);
  }
  return out;
}

export async function fetchCounts(
  client: SupabaseClient,
  region: Region,
  now: Date,
): Promise<{ open: number; today: number }> {
  const countries = REGION_COUNTRIES[region];
  const since = new Date(now.getTime() - WITHIN_MS["24h"]).toISOString();
  const [open, today] = await Promise.all([
    client.from("jobs_feed").select("id", { count: "exact", head: true }).in("country", countries),
    client
      .from("jobs_feed")
      .select("id", { count: "exact", head: true })
      .in("country", countries)
      .gte("first_seen_at", since),
  ]);
  if (open.error || today.error) throw new Error("count query failed");
  return { open: open.count ?? 0, today: today.count ?? 0 };
}

const SEASON_YEAR = /(Summer|Fall|Winter|Spring) (20\d\d)/;
const SEASON_ORDER = { Winter: 0, Spring: 1, Summer: 2, Fall: 3 } as const;

export function termOptions(terms: (string | null)[]): string[] {
  const found = new Map<string, number>();
  for (const t of terms) {
    const m = t?.match(SEASON_YEAR);
    if (m) {
      const season = m[1] as keyof typeof SEASON_ORDER;
      found.set(`${season} ${m[2]}`, Number(m[2]) * 4 + SEASON_ORDER[season]);
    }
  }
  return [...found.entries()].sort((a, b) => a[1] - b[1]).map(([label]) => label);
}

export async function fetchTermOptions(client: SupabaseClient, region: Region): Promise<string[]> {
  const { data, error } = await client
    .from("jobs_feed")
    .select("term")
    .in("country", REGION_COUNTRIES[region])
    .not("term", "is", null)
    .limit(5000);
  if (error) throw new Error(`terms query failed: ${error.message}`);
  return termOptions((data ?? []).map((r: { term: string | null }) => r.term));
}
