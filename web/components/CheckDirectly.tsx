import { DIRECT_COMPANIES } from "@/lib/direct";

export function CheckDirectly() {
  return (
    <details className="pb-3 text-[13px] text-slate">
      <summary className="cursor-pointer hover:text-ink">
        {DIRECT_COMPANIES.length} companies we can&apos;t scrape: check their sites directly
      </summary>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 pt-2">
        {DIRECT_COMPANIES.map((c) => (
          <li key={c.name}>
            <a
              href={c.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-graphite underline-offset-2 hover:text-ink hover:underline"
            >
              {c.name}
            </a>
          </li>
        ))}
      </ul>
    </details>
  );
}
