import { type Filters, PAGE_SIZE, toQuery } from "@/lib/filters";

export function Pagination({ filters, total }: { filters: Filters; total: number }) {
  const pages = Math.ceil(total / PAGE_SIZE);
  if (pages <= 1) return null;
  const link = (page: number) => `/${filters.region}${toQuery({ ...filters, page })}`;
  const btn =
    "rounded-control border border-divider bg-surface px-3 py-1.5 text-sm hover:border-input-steel";
  return (
    <nav
      aria-label="Pagination"
      className="flex items-center justify-between py-6 text-sm text-graphite"
    >
      {filters.page > 1 ? (
        <a href={link(filters.page - 1)} className={btn}>
          Previous
        </a>
      ) : (
        <span />
      )}
      <span>
        Page {filters.page} of {pages}
      </span>
      {filters.page < pages ? (
        <a href={link(filters.page + 1)} className={btn}>
          Next
        </a>
      ) : (
        <span />
      )}
    </nav>
  );
}
