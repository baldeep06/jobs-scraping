import { notFound } from "next/navigation";
import { FilterBar } from "@/components/FilterBar";
import { Hero } from "@/components/Hero";
import { JobList } from "@/components/JobList";
import { Pagination } from "@/components/Pagination";
import { RegionTabs } from "@/components/RegionTabs";
import { parseFilters, type SearchParams } from "@/lib/filters";
import { fetchCounts, fetchJobs, fetchSources, fetchTermOptions } from "@/lib/jobs";
import { supabase } from "@/lib/supabase";
import type { Region } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function RegionPage({
  params,
  searchParams,
}: {
  params: Promise<{ region: string }>;
  searchParams: Promise<SearchParams>;
}) {
  const { region } = await params;
  if (region !== "us" && region !== "ca") notFound();
  const filters = parseFilters(region as Region, await searchParams);
  const now = new Date();
  const client = supabase();
  const [{ rows, total }, counts, terms] = await Promise.all([
    fetchJobs(client, filters, now),
    fetchCounts(client, filters.region, now),
    fetchTermOptions(client, filters.region),
  ]);
  const sources = await fetchSources(
    client,
    rows.map((r) => r.id),
  );

  return (
    <>
      <Hero region={filters.region} counts={counts} filters={filters} />
      <main className="mx-auto max-w-[1280px] px-4 pb-16 md:px-8">
        <div className="pt-8">
          <RegionTabs filters={filters} />
          <FilterBar filters={filters} terms={terms} />
        </div>
        <p className="pb-3 text-[13px] text-slate">
          {total.toLocaleString("en-US")} {total === 1 ? "internship" : "internships"}
        </p>
        <JobList rows={rows} sources={sources} now={now} filters={filters} />
        <Pagination filters={filters} total={total} />
      </main>
    </>
  );
}
