import { Badge } from "@/components/Badge";
import { flagBadges, freshnessBadge, visaBadge } from "@/lib/badges";
import type { Filters } from "@/lib/filters";
import { companyInitial, faviconUrl, formatLocation, formatPay, relativeTime, safeUrl } from "@/lib/format";
import type { JobRow, JobSource } from "@/lib/types";

// Company | Role | Location | Term | Pay | Visa | Flags | Seen
const GRID =
  "md:grid md:grid-cols-[minmax(140px,1.1fr)_minmax(200px,2fr)_minmax(140px,1.2fr)_110px_110px_90px_minmax(120px,1.2fr)_90px] md:items-center md:gap-4";

const EVIDENCE_LABELS: Record<string, string> = {
  no_sponsorship: "No sponsorship",
  us_citizen_only: "US citizens only",
  clearance: "Security clearance",
  us_school_required: "US school only",
  sponsors: "Sponsors visas",
  canadian_coop_required: "Co-op enrolment",
  pay_listed: "Pay",
  grad_students_only: "Grad students",
  early_years_only: "1st/2nd year",
  eligibility_restricted: "Eligibility",
  relocation: "Relocation",
};

function evidenceLabel(key: string): string {
  if (key.startsWith("grad_year:")) return `Grad ${key.slice(10)}`;
  return EVIDENCE_LABELS[key] ?? key;
}

function Row({ job, sources, now }: { job: JobRow; sources: JobSource[]; now: Date }) {
  const url = safeUrl(job.best_url);
  const pay = formatPay(job.pay_hourly_min, job.pay_hourly_max, job.pay_currency);
  const icon = faviconUrl(job.company_domain);
  const mode = job.work_mode === "remote" || job.work_mode === "hybrid" ? job.work_mode : null;
  const flags = flagBadges(job);
  const evidence = Object.entries(job.evidence);
  return (
    <li className="border-b border-divider last:border-b-0">
      <details className="group">
        <summary className={`cursor-pointer px-4 py-3 hover:bg-canvas/60 md:px-6 ${GRID}`}>
          <div className="flex items-center gap-2 text-sm font-medium text-ink">
            {icon ? (
              <img src={icon} alt="" width={16} height={16} className="h-4 w-4 rounded-sm" />
            ) : (
              <span
                data-testid="company-initial"
                aria-hidden="true"
                className="flex h-4 w-4 shrink-0 items-center justify-center rounded-sm bg-divider text-[10px] font-semibold leading-none text-graphite"
              >
                {companyInitial(job.company_name)}
              </span>
            )}
            <span className="truncate">{job.company_name}</span>
          </div>
          <div className="mt-1 text-sm md:mt-0">
            {url ? (
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-ink hover:text-signal"
              >
                {job.title}
              </a>
            ) : (
              <span className="font-medium text-ink">{job.title}</span>
            )}
            <span className="ml-2 text-xs text-slate">{job.category}</span>
          </div>
          <div className="mt-1 text-sm text-graphite md:mt-0">
            {formatLocation(job)}
            {mode && <span className="ml-2 text-xs capitalize text-slate">{mode}</span>}
          </div>
          {/* On phones, empty term/pay are hidden and the badges share one wrapped line. */}
          <div className={`text-sm text-graphite ${job.term ? "" : "hidden md:block"}`}>
            {job.term ?? "—"}
          </div>
          <div
            className={`text-sm text-ink ${pay ? "" : "hidden md:block"}`}
            title={job.pay_raw ?? undefined}
          >
            {pay ?? <span className="text-slate">—</span>}
          </div>
          <div className="mr-2 mt-2 inline-flex md:mr-0 md:mt-0 md:flex">
            <Badge spec={visaBadge(job)} />
          </div>
          <div className="mr-2 mt-2 inline-flex flex-wrap gap-1 md:mr-0 md:mt-0 md:flex">
            {flags.map((b) => (
              <Badge key={b.label} spec={b} />
            ))}
          </div>
          <div className="mt-2 inline-flex flex-wrap items-center gap-2 md:mt-0 md:flex md:flex-col md:items-start md:gap-1">
            <Badge spec={freshnessBadge(job, now)} />
            <span className="text-xs text-slate">{relativeTime(job.first_seen_at, now)}</span>
          </div>
        </summary>
        <div className="grid gap-4 bg-canvas/50 px-4 py-4 text-sm text-graphite md:grid-cols-2 md:px-6">
          <div>
            <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-slate">
              Why these labels
            </h3>
            {evidence.length ? (
              <ul className="space-y-1.5">
                {evidence.map(([key, sentence]) => (
                  <li key={key}>
                    <span className="font-medium text-ink">{evidenceLabel(key)}:</span> {sentence}
                  </li>
                ))}
              </ul>
            ) : (
              <p>The posting doesn&apos;t mention visas, pay or eligibility limits.</p>
            )}
          </div>
          <div className="space-y-2">
            <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-slate">Details</h3>
            <p>
              First seen {new Date(job.first_seen_at).toUTCString().slice(5, 16)} · location as
              posted: {job.location_raw || "—"}
            </p>
            {job.pay_raw && <p>Pay as posted: {job.pay_raw}</p>}
            {job.repost_count > 0 && (
              <p>Posted before: this role has been reposted {job.repost_count}×.</p>
            )}
            {job.h1b_count != null && (
              <p>
                {job.company_name} filed {job.h1b_count.toLocaleString("en-US")} H-1B LCAs
                recently.
              </p>
            )}
            {sources.length > 0 && (
              <p>
                Listed on:{" "}
                {sources.map((s, i) => {
                  const href = safeUrl(s.url);
                  return (
                    <span key={`${s.source}-${s.url}`}>
                      {i > 0 && ", "}
                      {href ? (
                        <a
                          href={href}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="underline hover:text-signal"
                        >
                          {s.source}
                        </a>
                      ) : (
                        s.source
                      )}
                    </span>
                  );
                })}
              </p>
            )}
          </div>
        </div>
      </details>
    </li>
  );
}

export function JobList({
  rows,
  sources,
  now,
  filters,
}: {
  rows: JobRow[];
  sources: Record<string, JobSource[]>;
  now: Date;
  filters: Filters;
}) {
  if (rows.length === 0) {
    return (
      <div className="rounded-card bg-surface px-6 py-16 text-center shadow-subtle">
        <p className="font-display text-xl font-semibold">No internships match these filters</p>
        <a
          href={`/${filters.region}`}
          className="mt-3 inline-block text-sm text-signal hover:underline"
        >
          Clear filters
        </a>
      </div>
    );
  }
  return (
    <div className="overflow-hidden rounded-card bg-surface shadow-subtle">
      <div
        className={`hidden border-b border-divider px-6 py-3 text-[13px] font-medium text-slate ${GRID}`}
      >
        <span>Company</span>
        <span>Role</span>
        <span>Location</span>
        <span>Term</span>
        <span>Pay</span>
        <span>Visa</span>
        <span>Flags</span>
        <span>Seen</span>
      </div>
      <ul>
        {rows.map((job) => (
          <Row key={job.id} job={job} sources={sources[job.id] ?? []} now={now} />
        ))}
      </ul>
    </div>
  );
}
