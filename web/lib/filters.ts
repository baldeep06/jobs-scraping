import type { Region, VisaStatus } from "@/lib/types";

export const CATEGORIES = [
  "SWE",
  "Data/ML",
  "Hardware/Embedded",
  "PM",
  "Design",
  "Quant",
  "IT/Security",
  "Other-tech",
] as const;
export const WITHIN = ["1h", "24h", "7d", "all"] as const;
export type Within = (typeof WITHIN)[number];
export const PAGE_SIZE = 50;
const VISA: VisaStatus[] = ["open", "unknown", "blocked"];
const TERM_RE = /^(Summer|Fall|Winter|Spring) 20\d\d$/;
const MAX_PAGE = 1000;

export type SearchParams = Record<string, string | string[] | undefined>;

export interface Filters {
  region: Region;
  q: string;
  category: string | null;
  term: string | null;
  visa: VisaStatus[];
  within: Within;
  fresh: boolean;
  pay: boolean;
  remote: boolean;
  sort: "new" | "pay";
  page: number;
}

export function defaultVisa(region: Region): VisaStatus[] {
  return region === "us" ? ["open", "unknown"] : ["open", "unknown", "blocked"];
}

const first = (v: string | string[] | undefined): string | undefined =>
  Array.isArray(v) ? v[0] : v;

/** Keeps letters, digits, spaces and . + # / - ; drops PostgREST/LIKE metacharacters. */
export function sanitizeSearch(q: string): string {
  return q
    .replace(/[^\p{L}\p{N} .+#/-]/gu, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 80);
}

export function parseFilters(region: Region, params: SearchParams): Filters {
  const visaParam = first(params.visa);
  const visa = visaParam
    ? VISA.filter((v) => visaParam.split(",").includes(v))
    : defaultVisa(region);
  const category = first(params.category) ?? "";
  const term = first(params.term) ?? "";
  const within = first(params.within) ?? "";
  const page = Number.parseInt(first(params.page) ?? "1", 10);
  return {
    region,
    q: sanitizeSearch(first(params.q) ?? ""),
    category: (CATEGORIES as readonly string[]).includes(category) ? category : null,
    term: TERM_RE.test(term) ? term : null,
    visa: visa.length ? visa : defaultVisa(region),
    within: (WITHIN as readonly string[]).includes(within) ? (within as Within) : "all",
    fresh: first(params.fresh) === "1",
    pay: first(params.pay) === "1",
    remote: first(params.remote) === "1",
    sort: first(params.sort) === "pay" ? "pay" : "new",
    page: Number.isFinite(page) && page >= 1 ? Math.min(page, MAX_PAGE) : 1,
  };
}

/** Where to send a request for a page past the end (results shrink as jobs close), or null. */
export function lastPageRedirect(f: Filters, rowCount: number, total: number): string | null {
  if (rowCount > 0 || total === 0 || f.page === 1) return null;
  return `/${f.region}${toQuery({ ...f, page: Math.ceil(total / PAGE_SIZE) })}`;
}

export function toQuery(f: Filters): string {
  const p = new URLSearchParams();
  if (f.q) p.set("q", f.q);
  if (f.category) p.set("category", f.category);
  if (f.term) p.set("term", f.term);
  if (f.visa.join(",") !== defaultVisa(f.region).join(",")) p.set("visa", f.visa.join(","));
  if (f.within !== "all") p.set("within", f.within);
  if (f.fresh) p.set("fresh", "1");
  if (f.pay) p.set("pay", "1");
  if (f.remote) p.set("remote", "1");
  if (f.sort !== "new") p.set("sort", f.sort);
  if (f.page !== 1) p.set("page", String(f.page));
  const s = p.toString();
  return s ? `?${s}` : "";
}
