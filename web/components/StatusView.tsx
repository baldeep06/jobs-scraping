import { Badge } from "@/components/Badge";
import type { WorkflowHealth } from "@/lib/health";

interface Props {
  health: WorkflowHealth[];
  companiesByTier: Record<string, number>;
  openJobs: { us: number; ca: number };
}

export function StatusView({ health, companiesByTier, openJobs }: Props) {
  return (
    <main className="mx-auto max-w-[1280px] px-4 py-10 md:px-8">
      <h1 className="font-display text-2xl font-semibold tracking-tight">Status</h1>
      <p className="mt-1 text-sm text-graphite">
        A source is degraded if it has not finished a run within its window.
      </p>

      <section className="mt-6 grid gap-3">
        {health.map((h) => (
          <div
            key={h.workflow}
            className="flex flex-wrap items-center justify-between gap-3 rounded-card bg-surface px-5 py-4 shadow-subtle"
          >
            <div>
              <p className="font-display text-base font-semibold">{h.workflow}</p>
              <p className="text-sm text-graphite">
                {h.minutesAgo === null
                  ? "never recorded in the last 24 h"
                  : `last run ${h.minutesAgo} min ago`}
                {" · "}window {h.windowMinutes} min{" · "}errors in last run: {h.errors}
              </p>
            </div>
            <Badge
              spec={
                h.degraded
                  ? { label: "Degraded", tone: "tangerine" }
                  : { label: "Healthy", tone: "signal" }
              }
            />
          </div>
        ))}
      </section>

      <section className="mt-6 grid gap-3 md:grid-cols-2">
        <div className="rounded-card bg-surface px-5 py-4 shadow-subtle">
          <p className="font-display text-base font-semibold">Open internships</p>
          <p className="mt-1 text-sm text-graphite">US {openJobs.us} · Canada {openJobs.ca}</p>
        </div>
        <div className="rounded-card bg-surface px-5 py-4 shadow-subtle">
          <p className="font-display text-base font-semibold">Companies by tier</p>
          <p className="mt-1 text-sm text-graphite">
            {Object.entries(companiesByTier)
              .map(([tier, n]) => `${tier} ${n}`)
              .join(" · ")}
          </p>
        </div>
      </section>
    </main>
  );
}
