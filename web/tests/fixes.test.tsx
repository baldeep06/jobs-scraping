import { renderToStaticMarkup } from "react-dom/server";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";
import RegionError from "@/app/[region]/error";
import { FilterBar } from "@/components/FilterBar";
import { JobList } from "@/components/JobList";
import { lastPageRedirect, parseFilters } from "@/lib/filters";
import { fetchCounts, fetchJobs } from "@/lib/jobs";
import { fakeClient } from "./fakeClient";
import { makeJob } from "./fixtures";

const NOW = new Date("2026-10-07T12:00:00Z");

describe("pages past the end", () => {
  it("fetchJobs returns no rows plus the real total instead of throwing", async () => {
    const { client, log } = fakeClient((_calls, head) =>
      head
        ? { count: 74 }
        : { error: { code: "PGRST103", message: "Requested range not satisfiable" } },
    );
    const result = await fetchJobs(client, parseFilters("us", { page: "3" }), NOW);
    expect(result).toEqual({ rows: [], total: 74 });
    const countCalls = log[1];
    expect(countCalls).toContainEqual(["in", "visa_status", ["open", "unknown"]]);
    expect(countCalls.some((c) => c[0] === "range")).toBe(false);
  });

  it("other errors still throw", async () => {
    const { client } = fakeClient(() => ({ error: { code: "42P01", message: "boom" } }));
    await expect(fetchJobs(client, parseFilters("us", {}), NOW)).rejects.toThrow("boom");
  });

  it("redirects an empty page beyond the end to the last page", () => {
    const f = parseFilters("us", { page: "9", category: "SWE" });
    expect(lastPageRedirect(f, 0, 74)).toBe("/us?category=SWE&page=2");
    expect(lastPageRedirect(parseFilters("us", { page: "9" }), 0, 30)).toBe("/us");
    expect(lastPageRedirect(f, 5, 74)).toBeNull();
    expect(lastPageRedirect(f, 0, 0)).toBeNull();
    expect(lastPageRedirect(parseFilters("us", {}), 0, 74)).toBeNull();
  });
});

describe("hero counts", () => {
  it("count only what the region shows by default", async () => {
    const { client, log } = fakeClient(() => ({ count: 1 }));
    await fetchCounts(client, "us", NOW);
    for (const calls of log) {
      expect(calls).toContainEqual(["in", "visa_status", ["open", "unknown"]]);
    }
  });
});

describe("error boundary", () => {
  it("Retry re-fetches with retry(), not reset()", () => {
    const retry = vi.fn();
    const reset = vi.fn();
    const tree = RegionError({ error: new Error("x"), retry, reset }) as ReactElement;
    const find = (el: unknown): ReactElement | null => {
      if (!el || typeof el !== "object") return null;
      const e = el as ReactElement<{ children?: unknown; onClick?: () => void }>;
      if (e.type === "button") return e;
      const kids = ([] as unknown[]).concat(e.props?.children ?? []);
      for (const k of kids) {
        const hit = find(k);
        if (hit) return hit;
      }
      return null;
    };
    const button = find(tree) as ReactElement<{ onClick: () => void }>;
    button.props.onClick();
    expect(retry).toHaveBeenCalledOnce();
    expect(reset).not.toHaveBeenCalled();
  });
});

describe("filter dropdowns keep values that aren't standard options", () => {
  it("visa=blocked and an unlisted term stay selected", () => {
    const f = parseFilters("us", { visa: "blocked", term: "Fall 2026" });
    const html = renderToStaticMarkup(<FilterBar filters={f} terms={["Summer 2027"]} />);
    expect(html).toMatch(/<option value="blocked" selected="">/);
    expect(html).toMatch(/<option value="Fall 2026" selected="">/);
  });
});

describe("row details", () => {
  it("shows pay exactly as posted, reachable without hover", () => {
    const html = renderToStaticMarkup(
      <JobList rows={[makeJob()]} sources={{}} now={NOW} filters={parseFilters("ca", {})} />,
    );
    expect(html).toContain("Pay as posted: CA$30 - CA$38 per hour");
  });

  it("never links a non-http source URL", () => {
    const job = makeJob();
    const sources = {
      [job.id]: [{ job_id: job.id, source: "lever", url: "javascript:alert(1)", first_seen_at: "" }],
    };
    const html = renderToStaticMarkup(
      <JobList rows={[job]} sources={sources} now={NOW} filters={parseFilters("ca", {})} />,
    );
    expect(html).not.toContain("javascript:");
    expect(html).toContain("lever");
  });
});
