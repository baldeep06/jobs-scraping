import { describe, expect, it } from "vitest";
import { faviconUrl, formatLocation, formatPay, relativeTime, safeUrl } from "@/lib/format";

const NOW = new Date("2026-10-07T12:00:00Z");

describe("relativeTime", () => {
  it.each([
    ["2026-10-07T11:59:30Z", "just now"],
    ["2026-10-07T11:48:00Z", "12m ago"],
    ["2026-10-07T07:00:00Z", "5h ago"],
    ["2026-10-04T12:00:00Z", "3d ago"],
    ["2026-07-01T12:00:00Z", "3mo ago"],
    ["2026-10-07T12:05:00Z", "just now"],
  ])("%s → %s", (iso, expected) => {
    expect(relativeTime(iso, NOW)).toBe(expected);
  });
});

describe("formatPay", () => {
  it("formats ranges with currency symbols", () => {
    expect(formatPay(30, 38, "CAD")).toBe("C$30–38/h");
    expect(formatPay(28, 35, "USD")).toBe("$28–35/h");
  });
  it("collapses equal bounds and trims decimals", () => {
    expect(formatPay(57.7, 57.7, "USD")).toBe("$57.70/h");
    expect(formatPay(33.65, 40.87, "CAD")).toBe("C$33.65–40.87/h");
  });
  it("handles a missing bound and no pay", () => {
    expect(formatPay(null, 50, "USD")).toBe("$50/h");
    expect(formatPay(null, null, null)).toBeNull();
  });
});

describe("formatLocation", () => {
  it("lists up to two places then counts the rest", () => {
    expect(
      formatLocation({
        location_raw: "",
        location_unclear: false,
        locations: [
          { city: "New York", region: "NY", country: "US" },
          { city: "Seattle", region: "WA", country: "US" },
          { city: null, region: null, country: "CA" },
        ],
      }),
    ).toBe("New York, NY · Seattle, WA · +1 more");
  });
  it("names the country when there is no city", () => {
    expect(
      formatLocation({
        location_raw: "Remote - Canada",
        location_unclear: false,
        locations: [{ city: null, region: null, country: "CA" }],
      }),
    ).toBe("Canada");
  });
  it("says when the location is unclear", () => {
    expect(formatLocation({ location_raw: "Remote", location_unclear: true, locations: [] })).toBe(
      "Location unclear",
    );
  });
});

describe("safeUrl", () => {
  it("allows http and https only", () => {
    expect(safeUrl("https://jobs.lever.co/x/1")).toBe("https://jobs.lever.co/x/1");
    expect(safeUrl("http://example.com/a")).toBe("http://example.com/a");
    expect(safeUrl("javascript:alert(1)")).toBeNull();
    expect(safeUrl("JaVaScRiPt:alert(1)")).toBeNull();
    expect(safeUrl("data:text/html,hi")).toBeNull();
    expect(safeUrl("not a url")).toBeNull();
    expect(safeUrl(null)).toBeNull();
  });
});

describe("faviconUrl", () => {
  it("uses Google's favicon service", () => {
    expect(faviconUrl("stripe.com")).toBe(
      "https://www.google.com/s2/favicons?domain=stripe.com&sz=64",
    );
    expect(faviconUrl(null)).toBeNull();
  });
});
