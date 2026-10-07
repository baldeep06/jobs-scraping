import { describe, expect, it } from "vitest";
import { defaultVisa, parseFilters, sanitizeSearch, toQuery } from "@/lib/filters";

describe("parseFilters", () => {
  it("uses region defaults", () => {
    const us = parseFilters("us", {});
    expect(us).toEqual({
      region: "us",
      q: "",
      category: null,
      term: null,
      visa: ["open", "unknown"],
      within: "all",
      fresh: false,
      pay: false,
      remote: false,
      sort: "new",
      page: 1,
    });
    expect(parseFilters("ca", {}).visa).toEqual(["open", "unknown", "blocked"]);
  });

  it("reads valid params", () => {
    const f = parseFilters("us", {
      q: "stripe",
      category: "Data/ML",
      term: "Summer 2027",
      visa: "open,blocked",
      within: "24h",
      fresh: "1",
      pay: "1",
      remote: "1",
      sort: "pay",
      page: "3",
    });
    expect(f).toMatchObject({
      q: "stripe",
      category: "Data/ML",
      term: "Summer 2027",
      visa: ["open", "blocked"],
      within: "24h",
      fresh: true,
      pay: true,
      remote: true,
      sort: "pay",
      page: 3,
    });
  });

  it("falls back to defaults for garbage", () => {
    const f = parseFilters("us", {
      visa: "foo",
      page: "-3",
      category: "<script>",
      term: "x%",
      within: "forever",
      sort: "drop table",
      fresh: "yes",
    });
    expect(f).toEqual(parseFilters("us", {}));
  });

  it("takes the first of repeated params and caps the page", () => {
    expect(parseFilters("us", { q: ["a", "b"], page: "999999" })).toMatchObject({
      q: "a",
      page: 1000,
    });
  });
});

describe("sanitizeSearch", () => {
  it("strips PostgREST and LIKE metacharacters", () => {
    expect(sanitizeSearch('a,b(c)"d%e*f\\g')).toBe("a b c d e f g");
    expect(sanitizeSearch("  C++ / .NET intern  ")).toBe("C++ / .NET intern");
    expect(sanitizeSearch("x".repeat(200))).toHaveLength(80);
  });
});

describe("toQuery", () => {
  it("omits defaults", () => {
    expect(toQuery(parseFilters("us", {}))).toBe("");
    expect(toQuery(parseFilters("ca", {}))).toBe("");
  });

  it("round-trips non-default values", () => {
    const params = { q: "data", category: "SWE", visa: "open", fresh: "1", sort: "pay", page: "2" };
    const f = parseFilters("us", params);
    const query = toQuery(f);
    expect(query).toBe("?q=data&category=SWE&visa=open&fresh=1&sort=pay&page=2");
    const back = Object.fromEntries(new URLSearchParams(query.slice(1)));
    expect(parseFilters("us", back)).toEqual(f);
  });

  it("encodes values", () => {
    expect(toQuery({ ...parseFilters("us", {}), category: "Data/ML" })).toBe(
      "?category=Data%2FML",
    );
  });
});

describe("defaultVisa", () => {
  it("hides blocked only in the US", () => {
    expect(defaultVisa("us")).toEqual(["open", "unknown"]);
    expect(defaultVisa("ca")).toEqual(["open", "unknown", "blocked"]);
  });
});
