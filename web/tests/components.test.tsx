import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { FilterBar } from "@/components/FilterBar";
import { JobList } from "@/components/JobList";
import { Pagination } from "@/components/Pagination";
import { RegionTabs } from "@/components/RegionTabs";
import { parseFilters } from "@/lib/filters";
import { makeJob } from "./fixtures";

const NOW = new Date("2026-10-07T12:00:00Z");
const US = parseFilters("us", {});

describe("JobList", () => {
  it("renders a row with link, pay, visa, freshness and details", () => {
    const job = makeJob({
      visa_status: "blocked",
      visa_signals: ["no_sponsorship"],
      evidence: { no_sponsorship: "We will not sponsor visas." },
      first_seen_at: "2026-10-07T11:00:00Z",
    });
    const sources = {
      [job.id]: [
        { job_id: job.id, source: "greenhouse", url: job.best_url, first_seen_at: job.first_seen_at },
      ],
    };
    const html = renderToStaticMarkup(
      <JobList rows={[job]} sources={sources} now={NOW} filters={US} />,
    );
    expect(html).toContain('href="https://boards.greenhouse.io/acme/jobs/1"');
    expect(html).toContain("Software Engineer Intern");
    expect(html).toContain("C$30–38/h");
    expect(html).toContain("Blocked");
    expect(html).toContain("New");
    expect(html).toContain("1h ago");
    expect(html).toContain("We will not sponsor visas.");
    expect(html).toContain("greenhouse");
    expect(html).toContain("<details");
  });

  it("never links a non-http URL", () => {
    const html = renderToStaticMarkup(
      <JobList
        rows={[makeJob({ best_url: "javascript:alert(1)" })]}
        sources={{}}
        now={NOW}
        filters={US}
      />,
    );
    expect(html).not.toContain("javascript:");
    expect(html).toContain("Software Engineer Intern");
  });

  it("shows an empty state with a clear-filters link", () => {
    const filtered = parseFilters("us", { category: "Quant" });
    const html = renderToStaticMarkup(
      <JobList rows={[]} sources={{}} now={NOW} filters={filtered} />,
    );
    expect(html).toContain("No internships match");
    expect(html).toContain('href="/us"');
  });

  it("shows Location unclear", () => {
    const html = renderToStaticMarkup(
      <JobList
        rows={[makeJob({ locations: [], location_unclear: true, country: "UNKNOWN" })]}
        sources={{}}
        now={NOW}
        filters={US}
      />,
    );
    expect(html).toContain("Location unclear");
  });
});

describe("RegionTabs", () => {
  it("keeps filters but resets visa defaults and page when switching", () => {
    const f = parseFilters("us", { category: "SWE", page: "3" });
    const html = renderToStaticMarkup(<RegionTabs filters={f} />);
    expect(html).toContain('href="/ca?category=SWE"');
    expect(html).toContain('aria-current="page"');
  });
});

describe("Pagination", () => {
  it("links previous and next pages", () => {
    const f = parseFilters("us", { page: "2" });
    const html = renderToStaticMarkup(<Pagination filters={f} total={160} />);
    expect(html).toContain('href="/us"');
    expect(html).toContain('href="/us?page=3"');
    expect(html).toContain("Page 2 of 4");
  });

  it("renders nothing for a single page", () => {
    expect(renderToStaticMarkup(<Pagination filters={US} total={10} />)).toBe("");
  });
});

describe("FilterBar", () => {
  it("is a GET form that preserves current choices", () => {
    const f = parseFilters("us", { category: "PM", fresh: "1", term: "Summer 2027" });
    const html = renderToStaticMarkup(<FilterBar filters={f} terms={["Summer 2027"]} />);
    expect(html).toContain('method="get"');
    expect(html).toContain('id="filters"');
    expect(html).toMatch(/<option value="PM" selected="">/);
    expect(html).toMatch(/<option value="Summer 2027" selected="">/);
    expect(html).toMatch(/<input[^>]*name="fresh"[^>]*checked=""/);
  });
});

describe("company icon", () => {
  it("shows the site's favicon when the company has a domain", () => {
    const html = renderToStaticMarkup(
      <JobList rows={[makeJob({ company_domain: "stripe.com" })]} sources={{}} now={NOW} filters={US} />,
    );
    expect(html).toContain("favicons?domain=stripe.com");
  });

  it("falls back to a letter tile for a company without a domain", () => {
    const html = renderToStaticMarkup(
      <JobList
        rows={[makeJob({ company_domain: null, company_name: "Zeta Labs" })]}
        sources={{}}
        now={NOW}
        filters={US}
      />,
    );
    expect(html).not.toContain("favicons");
    expect(html).toContain('data-testid="company-initial"');
    expect(html).toContain(">Z<");
  });
});
