import type { JobRow } from "@/lib/types";

export type Tone = "signal" | "sky" | "tangerine" | "orchid" | "apricot" | "neutral";

export interface BadgeSpec {
  label: string;
  tone: Tone;
  title?: string;
}

const DAY_MS = 24 * 60 * 60 * 1000;
const VISA_EVIDENCE_ORDER = [
  "no_sponsorship",
  "us_citizen_only",
  "clearance",
  "us_school_required",
  "sponsors",
];

export function visaBadge(job: JobRow): BadgeSpec {
  const reason = VISA_EVIDENCE_ORDER.find((s) => job.visa_signals.includes(s));
  const title = reason ? job.evidence[reason] : undefined;
  if (job.visa_status === "blocked") return { label: "Blocked", tone: "tangerine", title };
  if (job.visa_status === "open") return { label: "Open", tone: "sky", title };
  return { label: "Unknown", tone: "neutral", title };
}

const SIGNAL_BADGES: [string, string, Tone][] = [
  ["clearance", "Clearance", "tangerine"],
  ["us_school_required", "US school only", "tangerine"],
  ["canadian_coop_required", "Co-op enrolment", "apricot"],
];
const FLAG_BADGES: [string, string, Tone][] = [
  ["grad_students_only", "Grad students", "orchid"],
  ["early_years_only", "1st/2nd year", "orchid"],
  ["eligibility_restricted", "Restricted eligibility", "orchid"],
];

export function flagBadges(job: JobRow): BadgeSpec[] {
  const out: BadgeSpec[] = [];
  for (const [key, label, tone] of SIGNAL_BADGES) {
    if (job.visa_signals.includes(key)) out.push({ label, tone, title: job.evidence[key] });
  }
  for (const [key, label, tone] of FLAG_BADGES) {
    if (job.flags.includes(key)) out.push({ label, tone, title: job.evidence[key] });
  }
  for (const flag of job.flags.filter((f) => f.startsWith("grad_year:")).sort()) {
    out.push({
      label: `Grad ${flag.slice("grad_year:".length)}`,
      tone: "neutral",
      title: job.evidence[flag],
    });
  }
  if (job.flags.includes("relocation")) {
    out.push({ label: "Relocation", tone: "sky", title: job.evidence.relocation });
  }
  return out;
}

export function freshnessBadge(job: JobRow, now: Date): BadgeSpec {
  const recent = now.getTime() - new Date(job.first_seen_at).getTime() < DAY_MS;
  if (recent && (job.freshness === "fresh" || job.freshness === "recurring")) {
    return { label: "New", tone: "signal" };
  }
  switch (job.freshness) {
    case "repost":
      return {
        label: job.repost_count > 1 ? `Repost ×${job.repost_count}` : "Repost",
        tone: "orchid",
      };
    case "reopened":
      return { label: "Reopened", tone: "orchid" };
    case "refreshed":
      return { label: "Date bumped", tone: "neutral" };
    case "recurring":
      return { label: "Returning role", tone: "neutral" };
    default:
      return { label: "Fresh", tone: "neutral" };
  }
}
