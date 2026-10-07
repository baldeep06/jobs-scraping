import type { BadgeSpec, Tone } from "@/lib/badges";

const TONES: Record<Tone, string> = {
  signal: "bg-signal border-signal text-white",
  sky: "bg-blue-mist border-sky-edge text-ink",
  tangerine: "bg-peach-paper border-tangerine-edge text-ink",
  orchid: "bg-lilac-wash border-orchid-edge text-ink",
  apricot: "bg-apricot border-tangerine-edge text-ink",
  neutral: "bg-canvas border-divider text-graphite",
};

export function Badge({ spec }: { spec: BadgeSpec }) {
  return (
    <span
      title={spec.title}
      className={`inline-flex items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium ${TONES[spec.tone]}`}
    >
      {spec.label}
    </span>
  );
}
