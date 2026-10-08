import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { StatusView } from "@/components/StatusView";
import type { WorkflowHealth } from "@/lib/health";

const health: WorkflowHealth[] = [
  { workflow: "scrape-hot", lastFinishedAt: "2026-10-07T11:55:00Z", minutesAgo: 5, windowMinutes: 60, degraded: false, errors: 2 },
  { workflow: "scrape-sweep", lastFinishedAt: null, minutesAgo: null, windowMinutes: 120, degraded: true, errors: 0 },
];

describe("StatusView", () => {
  it("shows healthy and degraded workflows and the counts", () => {
    const html = renderToStaticMarkup(
      <StatusView
        health={health}
        companiesByTier={{ hot: 95, warm: 846 }}
        openJobs={{ us: 300, ca: 168 }}
      />,
    );
    expect(html).toContain("Healthy");
    expect(html).toContain("Degraded");
    expect(html).toContain("scrape-sweep");
    expect(html).toContain("never");
    expect(html).toContain("95");
    expect(html).toContain("168");
  });
});
