import type { Filters } from "@/lib/filters";
import type { Region } from "@/lib/types";

const NAMES: Record<Region, string> = { us: "the US", ca: "Canada" };

export function Hero({
  region,
  counts,
  filters,
}: {
  region: Region;
  counts: { open: number; today: number };
  filters: Filters;
}) {
  return (
    <section className="bg-horizon">
      <div className="mx-auto max-w-[1280px] px-4 py-12 md:px-8 md:py-16">
        <h1 className="font-display text-4xl font-semibold tracking-[-1.2px] md:text-6xl md:tracking-[-1.5px]">
          Tech internships in {NAMES[region]}
        </h1>
        <p className="mt-3 text-base text-graphite">
          {counts.open.toLocaleString("en-US")} open · {counts.today.toLocaleString("en-US")} new
          in the last 24 hours · updated every 5 minutes
        </p>
        <div className="relative mt-6 max-w-2xl">
          <input
            form="filters"
            type="search"
            name="q"
            defaultValue={filters.q}
            placeholder="Search roles or companies"
            aria-label="Search roles or companies"
            className="w-full rounded-control border border-input-steel bg-surface py-3 pl-4 pr-24 text-base outline-none focus:border-signal"
          />
          <button
            form="filters"
            type="submit"
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded-control bg-signal px-3.5 pb-[9px] pt-[7px] text-sm font-medium text-white"
          >
            Search
          </button>
        </div>
      </div>
    </section>
  );
}
