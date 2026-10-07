export type Region = "us" | "ca";
export type Country = "CA" | "US" | "BOTH" | "UNKNOWN";
export type VisaStatus = "open" | "blocked" | "unknown";
export type Freshness = "fresh" | "repost" | "reopened" | "refreshed" | "recurring";
export type WorkMode = "onsite" | "hybrid" | "remote" | "unknown";

export interface Loc {
  city: string | null;
  region: string | null;
  country: "CA" | "US";
}

/** One row of the `jobs_feed` view (only the columns the site uses). */
export interface JobRow {
  id: string;
  title: string;
  company_name: string;
  company_domain: string | null;
  category: string;
  term: string | null;
  location_raw: string;
  locations: Loc[];
  country: Country;
  work_mode: WorkMode;
  location_unclear: boolean;
  pay_hourly_min: number | null;
  pay_hourly_max: number | null;
  pay_currency: string | null;
  pay_raw: string | null;
  visa_status: VisaStatus;
  visa_signals: string[];
  flags: string[];
  evidence: Record<string, string>;
  freshness: Freshness;
  repost_count: number;
  first_seen_at: string;
  best_url: string;
  h1b_count: number | null;
}

export interface JobSource {
  job_id: string;
  source: string;
  url: string;
  first_seen_at: string;
}
