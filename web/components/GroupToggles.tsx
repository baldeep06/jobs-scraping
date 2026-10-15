import { type Filters, GROUPS, type Group, toggleGroup, toQuery } from "@/lib/filters";

export function GroupToggles({
  filters,
  counts,
}: {
  filters: Filters;
  counts: Partial<Record<Group, number>>;
}) {
  return (
    <nav aria-label="Company groups" className="flex flex-wrap items-center gap-2 pb-1">
      {GROUPS.map(([key, label]) => {
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
    </nav>
  );
}
