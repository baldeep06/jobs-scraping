export const HEALTH_WINDOWS: Record<string, number> = { "scrape-hot": 60, "scrape-sweep": 120 };

export interface RunRow {
  workflow: string;
  finished_at: string;
  errors: number;
}

export interface WorkflowHealth {
  workflow: string;
  lastFinishedAt: string | null;
  minutesAgo: number | null;
  windowMinutes: number;
  degraded: boolean;
  errors: number;
}

/** Latest run per workflow; degraded when it is older than its window (or missing). */
export function workflowHealth(runs: RunRow[], now: Date): WorkflowHealth[] {
  return Object.entries(HEALTH_WINDOWS).map(([workflow, windowMinutes]) => {
    const latest = runs
      .filter((r) => r.workflow === workflow)
      .sort((a, b) => b.finished_at.localeCompare(a.finished_at))[0];
    const minutesAgo = latest
      ? Math.round((now.getTime() - new Date(latest.finished_at).getTime()) / 60_000)
      : null;
    return {
      workflow,
      lastFinishedAt: latest?.finished_at ?? null,
      minutesAgo,
      windowMinutes,
      degraded: minutesAgo === null || minutesAgo > windowMinutes,
      errors: latest?.errors ?? 0,
    };
  });
}
