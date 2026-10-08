import { describe, expect, it } from "vitest";
import { workflowHealth } from "@/lib/health";

const NOW = new Date("2026-10-07T12:00:00Z");
const ago = (m: number) => new Date(NOW.getTime() - m * 60_000).toISOString();

describe("workflowHealth", () => {
  it("uses the latest run per workflow and flags stale or missing ones", () => {
    const h = workflowHealth(
      [
        { workflow: "scrape-hot", finished_at: ago(200), errors: 0 },
        { workflow: "scrape-hot", finished_at: ago(10), errors: 3 },
      ],
      NOW,
    );
    const hot = h.find((x) => x.workflow === "scrape-hot")!;
    const sweep = h.find((x) => x.workflow === "scrape-sweep")!;
    expect(hot).toMatchObject({ degraded: false, minutesAgo: 10, errors: 3 });
    expect(sweep).toMatchObject({ degraded: true, lastFinishedAt: null, minutesAgo: null });
  });

  it("degrades once the window has passed", () => {
    const h = workflowHealth([{ workflow: "scrape-hot", finished_at: ago(61), errors: 0 }], NOW);
    expect(h.find((x) => x.workflow === "scrape-hot")!.degraded).toBe(true);
  });
});
