import { CATEGORIES, type Filters } from "@/lib/filters";

const select =
  "rounded-control border border-input-steel bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-signal";
const VISA_OPTIONS: [string, string][] = [
  ["open,unknown", "Hide blocked"],
  ["open", "Open only"],
  ["open,unknown,blocked", "Show all"],
];
const WITHIN_OPTIONS: [string, string][] = [
  ["all", "Any time"],
  ["1h", "Last hour"],
  ["24h", "Last 24 hours"],
  ["7d", "Last 7 days"],
];

function Check({ name, label, checked }: { name: string; label: string; checked: boolean }) {
  return (
    <label className="flex items-center gap-2 text-sm text-graphite">
      <input
        type="checkbox"
        name={name}
        value="1"
        defaultChecked={checked}
        className="accent-signal"
      />
      {label}
    </label>
  );
}

export function FilterBar({ filters, terms }: { filters: Filters; terms: string[] }) {
  const visa = filters.visa.join(",");
  // A URL can hold values the dropdowns don't offer (visa=blocked, a term from the other
  // tab); list them so the select shows the truth and the next Apply keeps them.
  const visaOptions = VISA_OPTIONS.some(([v]) => v === visa)
    ? VISA_OPTIONS
    : [...VISA_OPTIONS, [visa, `Custom: ${filters.visa.join(", ")}`] as [string, string]];
  const termOptions = filters.term && !terms.includes(filters.term) ? [filters.term, ...terms] : terms;
  return (
    <form id="filters" method="get" className="flex flex-wrap items-center gap-3 py-4">
      <select
        name="category"
        defaultValue={filters.category ?? ""}
        aria-label="Category"
        className={select}
      >
        <option value="">All categories</option>
        {CATEGORIES.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>
      <select name="term" defaultValue={filters.term ?? ""} aria-label="Term" className={select}>
        <option value="">Any term</option>
        {termOptions.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>
      <select name="visa" defaultValue={visa} aria-label="Visa" className={select}>
        {visaOptions.map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </select>
      <select
        name="within"
        defaultValue={filters.within}
        aria-label="Posted within"
        className={select}
      >
        {WITHIN_OPTIONS.map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </select>
      <select name="sort" defaultValue={filters.sort} aria-label="Sort" className={select}>
        <option value="new">Newest</option>
        <option value="pay">Highest pay</option>
      </select>
      <Check name="fresh" label="Fresh only" checked={filters.fresh} />
      <Check name="pay" label="Pay listed" checked={filters.pay} />
      <Check name="remote" label="Remote" checked={filters.remote} />
      <button
        type="submit"
        className="rounded-control bg-signal px-3.5 pb-[9px] pt-[7px] text-sm font-medium text-white"
      >
        Apply
      </button>
      <a href={`/${filters.region}`} className="text-sm text-slate hover:text-ink">
        Reset
      </a>
    </form>
  );
}
