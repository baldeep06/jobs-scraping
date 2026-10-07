import { defaultVisa, type Filters, toQuery } from "@/lib/filters";
import type { Region } from "@/lib/types";

const TABS: [Region, string][] = [
  ["us", "United States"],
  ["ca", "Canada"],
];

export function RegionTabs({ filters }: { filters: Filters }) {
  return (
    <div role="tablist" className="flex gap-1 border-b border-divider">
      {TABS.map(([region, label]) => {
        const active = region === filters.region;
        const href = `/${region}${toQuery({ ...filters, region, page: 1, visa: defaultVisa(region) })}`;
        return (
          <a
            key={region}
            href={href}
            role="tab"
            aria-selected={active}
            aria-current={active ? "page" : undefined}
            className={`-mb-px rounded-t-nav border-b-2 px-4 py-2.5 text-sm font-medium ${
              active ? "border-signal text-ink" : "border-transparent text-slate hover:text-ink"
            }`}
          >
            {label}
          </a>
        );
      })}
    </div>
  );
}
