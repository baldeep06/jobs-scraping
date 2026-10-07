import type { JobRow } from "@/lib/types";

export function makeJob(overrides: Partial<JobRow> = {}): JobRow {
  return {
    id: "00000000-0000-4000-8000-000000000001",
    title: "Software Engineer Intern",
    company_name: "Acme",
    company_domain: "acme.com",
    category: "SWE",
    term: "Summer 2027",
    location_raw: "Toronto, ON",
    locations: [{ city: "Toronto", region: "ON", country: "CA" }],
    country: "CA",
    work_mode: "onsite",
    location_unclear: false,
    pay_hourly_min: 30,
    pay_hourly_max: 38,
    pay_currency: "CAD",
    pay_raw: "CA$30 - CA$38 per hour",
    visa_status: "open",
    visa_signals: [],
    flags: ["pay_listed"],
    evidence: {},
    freshness: "fresh",
    repost_count: 0,
    first_seen_at: "2026-10-07T10:00:00Z",
    best_url: "https://boards.greenhouse.io/acme/jobs/1",
    h1b_count: null,
    ...overrides,
  };
}
