"use client";

import { useEffect, useRef, useState } from "react";
import { companyInitial, faviconUrl } from "@/lib/format";

// Sites Google has no icon for come without a domain (the scraper checks), so only an icon that
// fails to load is left to catch here.
function missing(img: HTMLImageElement): boolean {
  return img.complete && img.naturalWidth === 0;
}

/** The company's favicon, or a tile with its initial when it has no domain or no icon. */
export function CompanyLogo({ name, domain }: { name: string; domain: string | null }) {
  const src = faviconUrl(domain);
  const ref = useRef<HTMLImageElement>(null);
  const [failed, setFailed] = useState(false);

  // An image that failed before hydration never fires onError for React, so look once mounted.
  useEffect(() => {
    if (ref.current && missing(ref.current)) setFailed(true);
  }, [src]);

  if (!src || failed) {
    return (
      <span
        data-testid="company-initial"
        aria-hidden="true"
        className="flex h-4 w-4 shrink-0 items-center justify-center rounded-sm bg-divider text-[10px] font-semibold leading-none text-graphite"
      >
        {companyInitial(name)}
      </span>
    );
  }
  return (
    <img
      ref={ref}
      src={src}
      alt=""
      width={16}
      height={16}
      className="h-4 w-4 shrink-0 rounded-sm"
      onError={() => setFailed(true)}
    />
  );
}
