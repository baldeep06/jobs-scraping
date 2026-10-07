"use client";

export default function RegionError({ reset }: { error: Error; reset: () => void }) {
  return (
    <main className="mx-auto max-w-[1280px] px-4 py-16 md:px-8">
      <div className="rounded-card bg-surface px-6 py-16 text-center shadow-subtle">
        <p className="font-display text-xl font-semibold">Couldn&apos;t load internships</p>
        <p className="mt-2 text-sm text-graphite">
          The database didn&apos;t respond. Try again in a moment.
        </p>
        <button
          type="button"
          onClick={reset}
          className="mt-4 rounded-control bg-signal px-3.5 pb-[9px] pt-[7px] text-sm font-medium text-white"
        >
          Retry
        </button>
      </div>
    </main>
  );
}
