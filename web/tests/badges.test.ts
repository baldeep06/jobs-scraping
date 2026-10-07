import { describe, expect, it } from "vitest";
import { flagBadges, freshnessBadge, visaBadge } from "@/lib/badges";
import { makeJob } from "./fixtures";

const NOW = new Date("2026-10-07T12:00:00Z");

describe("visaBadge", () => {
  it("maps statuses and explains with evidence", () => {
    expect(visaBadge(makeJob())).toEqual({ label: "Open", tone: "sky", title: undefined });
    expect(visaBadge(makeJob({ visa_status: "unknown" }))).toMatchObject({
      label: "Unknown",
      tone: "neutral",
    });
    const blocked = makeJob({
      visa_status: "blocked",
      visa_signals: ["clearance", "no_sponsorship"],
      evidence: { clearance: "Needs clearance.", no_sponsorship: "We will not sponsor visas." },
    });
    expect(visaBadge(blocked)).toEqual({
      label: "Blocked",
      tone: "tangerine",
      title: "We will not sponsor visas.",
    });
  });
});

describe("flagBadges", () => {
  it("orders badges and skips pay/work-mode flags", () => {
    const job = makeJob({
      visa_signals: ["canadian_coop_required", "clearance"],
      flags: ["grad_year:2027", "grad_year:2028", "hybrid", "pay_listed", "relocation"],
      evidence: { relocation: "Relocation assistance is provided." },
    });
    expect(flagBadges(job).map((b) => b.label)).toEqual([
      "Clearance",
      "Co-op enrolment",
      "Grad 2027",
      "Grad 2028",
      "Relocation",
    ]);
    expect(flagBadges(job).at(-1)?.title).toBe("Relocation assistance is provided.");
  });

  it("is empty when nothing applies", () => {
    expect(flagBadges(makeJob())).toEqual([]);
  });
});

describe("freshnessBadge", () => {
  it("marks jobs first seen in the last day as New", () => {
    expect(freshnessBadge(makeJob({ first_seen_at: "2026-10-07T01:00:00Z" }), NOW)).toEqual({
      label: "New",
      tone: "signal",
    });
  });

  it.each([
    [{ freshness: "repost" as const, repost_count: 1 }, "Repost"],
    [{ freshness: "repost" as const, repost_count: 3 }, "Repost ×3"],
    [{ freshness: "reopened" as const }, "Reopened"],
    [{ freshness: "refreshed" as const }, "Date bumped"],
    [{ freshness: "recurring" as const }, "Returning role"],
    [{ freshness: "fresh" as const }, "Fresh"],
  ])("labels older %o as %s", (overrides, label) => {
    const job = makeJob({ first_seen_at: "2026-10-01T00:00:00Z", ...overrides });
    expect(freshnessBadge(job, NOW).label).toBe(label);
  });

  it("does not call a recent repost New", () => {
    const job = makeJob({
      freshness: "repost",
      repost_count: 1,
      first_seen_at: "2026-10-07T11:00:00Z",
    });
    expect(freshnessBadge(job, NOW).label).toBe("Repost");
  });
});
