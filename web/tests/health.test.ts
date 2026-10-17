import { describe, expect, it } from "vitest";
import { HEALTH_WINDOWS, workflowHealth } from "@/lib/health";

const NOW = new Date("2026-10-07T12:00:00Z");
const ago = (m: number) => new Date(NOW.getTime() - m * 60_000).toISOString();

describe("workflowHealth", () => {
  it("uses the latest run per workflow and flags stale or missing ones", () => {
    const h = workflowHealth(
      [
        { workflow: "scrape-heavy", finished_at: ago(200), errors: 0, companies_polled: 5 },
        { workflow: "scrape-heavy", finished_at: ago(10), errors: 3, companies_polled: 5 },
      ],
      NOW,
    );
    const hot = h.find((x) => x.workflow === "scrape-heavy")!;
    const sweep = h.find((x) => x.workflow === "scrape-sweep")!;
    expect(hot).toMatchObject({ degraded: false, minutesAgo: 10, errors: 3 });
    expect(sweep).toMatchObject({ degraded: true, lastFinishedAt: null, minutesAgo: null });
  });

  it("degrades once the window has passed", () => {
    const h = workflowHealth([{ workflow: "scrape-heavy", finished_at: ago(31), errors: 0, companies_polled: 5 }], NOW);
    expect(h.find((x) => x.workflow === "scrape-heavy")!.degraded).toBe(true);
  });

  it("has a window for every lane and the sweep", () => {
    expect(Object.keys(HEALTH_WINDOWS).sort()).toEqual([
      "scrape-express",
      "scrape-fast",
      "scrape-heavy",
      "scrape-sweep",
    ]);
  });

  it("ignores runs where every company failed", () => {
    const h = workflowHealth(
      [
        { workflow: "scrape-heavy", finished_at: ago(20), errors: 0, companies_polled: 40 },
        { workflow: "scrape-heavy", finished_at: ago(5), errors: 40, companies_polled: 40 },
      ],
      NOW,
    );
    expect(h.find((x) => x.workflow === "scrape-heavy")).toMatchObject({
      degraded: false,
      minutesAgo: 20,
    });
    const onlyFailed = workflowHealth(
      [{ workflow: "scrape-heavy", finished_at: ago(5), errors: 40, companies_polled: 40 }],
      NOW,
    );
    expect(onlyFailed.find((x) => x.workflow === "scrape-heavy")!.degraded).toBe(true);
  });

  it("agrees with the scraper at the boundary: 30m20s is already degraded", () => {
    const at = new Date(NOW.getTime() - (30 * 60_000 + 20_000)).toISOString();
    const h = workflowHealth(
      [{ workflow: "scrape-heavy", finished_at: at, errors: 0, companies_polled: 5 }],
      NOW,
    );
    expect(h.find((x) => x.workflow === "scrape-heavy")!.degraded).toBe(true);
  });
});
