export const HEALTH_WINDOWS: Record<string, number> = { "scrape-hot": 60, "scrape-sweep": 120 };

export interface RunRow {
  workflow: string;
  finished_at: string;
  errors: number;
  companies_polled: number;
}

export interface WorkflowHealth {
  workflow: string;
  lastFinishedAt: string | null;
  minutesAgo: number | null;
  windowMinutes: number;
  degraded: boolean;
  errors: number;
}

/** A run where every polled company failed is not a successful run (same rule as the scraper). */
const succeeded = (r: RunRow) => !(r.companies_polled > 0 && r.errors >= r.companies_polled);

/** Latest successful run per workflow; degraded when it is older than its window (or missing). */
export function workflowHealth(runs: RunRow[], now: Date): WorkflowHealth[] {
  return Object.entries(HEALTH_WINDOWS).map(([workflow, windowMinutes]) => {
    const latest = runs
      .filter((r) => r.workflow === workflow && succeeded(r))
      .sort((a, b) => b.finished_at.localeCompare(a.finished_at))[0];
    const ageMs = latest ? now.getTime() - new Date(latest.finished_at).getTime() : null;
    const minutesAgo = ageMs === null ? null : Math.round(ageMs / 60_000);
    return {
      workflow,
      lastFinishedAt: latest?.finished_at ?? null,
      minutesAgo,
      windowMinutes,
      degraded: ageMs === null || ageMs > windowMinutes * 60_000,
      errors: latest?.errors ?? 0,
    };
  });
}
