import type { JobRow } from "@/lib/types";

export function relativeTime(iso: string, now: Date): string {
  const seconds = Math.max(0, Math.floor((now.getTime() - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

function money(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(2);
}

export function formatPay(
  min: number | null,
  max: number | null,
  currency: string | null,
): string | null {
  if (min == null && max == null) return null;
  const lo = (min ?? max) as number;
  const hi = (max ?? min) as number;
  const symbol = currency === "CAD" ? "C$" : "$";
  const range = lo === hi ? money(lo) : `${money(lo)}–${money(hi)}`;
  return `${symbol}${range}/h`;
}

const COUNTRY_NAMES = { CA: "Canada", US: "United States" } as const;

export function formatLocation(
  job: Pick<JobRow, "locations" | "location_unclear" | "location_raw">,
): string {
  if (job.locations.length === 0) {
    return job.location_unclear ? "Location unclear" : job.location_raw || "—";
  }
  const names = job.locations.map((l) =>
    l.city ? (l.region ? `${l.city}, ${l.region}` : l.city) : COUNTRY_NAMES[l.country],
  );
  const shown = names.slice(0, 2);
  const extra = names.length - shown.length;
  return extra > 0 ? `${shown.join(" · ")} · +${extra} more` : shown.join(" · ");
}

export function safeUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? url : null;
  } catch {
    return null;
  }
}

export function faviconUrl(domain: string | null): string | null {
  return domain
    ? `https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=64`
    : null;
}
