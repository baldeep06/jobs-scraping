import { type Filters, GROUPS, type Group, toggleGroup, toQuery } from "@/lib/filters";

const ROWS = [
  ["tech", "Tech"],
  ["hardware", "Hardware"],
  ["finance", "Finance"],
  ["industry", "Industry"],
] as const;

export function GroupToggles({
  filters,
  counts,
}: {
  filters: Filters;
  counts: Partial<Record<Group, number>>;
}) {
  return (
    <nav aria-label="Company groups" className="flex flex-col gap-2 pb-1">
      {ROWS.map(([kind, title]) => (
        <div key={kind} className="flex flex-wrap items-center gap-2">
          <span className="w-20 shrink-0 text-[12px] font-medium uppercase tracking-wide text-slate">
            {title}
          </span>
          {GROUPS.filter((g) => g[2] === kind).map(([key, label]) => {
            const on = filters.group.includes(key);
            return (
              <a
                key={key}
                href={`/${filters.region}${toQuery(toggleGroup(filters, key))}`}
                aria-pressed={on}
                className={`rounded-full border px-3 py-1 text-[13px] ${
                  on
                    ? "border-signal bg-signal text-white"
                    : "border-input-steel bg-surface text-graphite hover:text-ink"
                }`}
              >
                {label} <span className={on ? "text-white/80" : "text-slate"}>{counts[key] ?? 0}</span>
              </a>
            );
          })}
        </div>
      ))}
    </nav>
  );
}
