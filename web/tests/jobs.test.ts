import { describe, expect, it } from "vitest";
import { parseFilters } from "@/lib/filters";
import { applyFilters, type FilterableQuery, termOptions } from "@/lib/jobs";

type Call = [string, ...unknown[]];

class Recorder implements FilterableQuery {
  calls: Call[] = [];
  private rec(name: string, args: unknown[]): this {
    this.calls.push([name, ...args]);
    return this;
  }
  in(c: string, v: readonly unknown[]): this {
    return this.rec("in", [c, v]);
  }
  eq(c: string, v: unknown): this {
    return this.rec("eq", [c, v]);
  }
  ilike(c: string, p: string): this {
    return this.rec("ilike", [c, p]);
  }
  gte(c: string, v: string): this {
    return this.rec("gte", [c, v]);
  }
  not(c: string, o: string, v: unknown): this {
    return this.rec("not", [c, o, v]);
  }
  or(f: string): this {
    return this.rec("or", [f]);
  }
  order(c: string, o: { ascending: boolean; nullsFirst?: boolean }): this {
    return this.rec("order", [c, o]);
  }
  range(a: number, b: number): this {
    return this.rec("range", [a, b]);
  }
}

const NOW = new Date("2026-10-07T12:00:00Z");

describe("applyFilters", () => {
  it("applies region, default visa, newest-first and first page", () => {
    const q = applyFilters(new Recorder(), parseFilters("us", {}), NOW);
    expect(q.calls).toEqual([
      ["in", "country", ["US", "BOTH", "UNKNOWN"]],
      ["in", "visa_status", ["open", "unknown"]],
      ["order", "first_seen_at", { ascending: false }],
      ["range", 0, 49],
    ]);
  });

  it("includes BOTH and UNKNOWN in the Canada tab too", () => {
    const q = applyFilters(new Recorder(), parseFilters("ca", {}), NOW);
    expect(q.calls[0]).toEqual(["in", "country", ["CA", "BOTH", "UNKNOWN"]]);
  });

  it("applies every filter", () => {
    const f = parseFilters("ca", {
      q: "data",
      category: "SWE",
      term: "Fall 2026",
      visa: "open",
      within: "24h",
      fresh: "1",
      pay: "1",
      remote: "1",
      sort: "pay",
      page: "3",
    });
    expect(applyFilters(new Recorder(), f, NOW).calls).toEqual([
      ["in", "country", ["CA", "BOTH", "UNKNOWN"]],
      ["in", "visa_status", ["open"]],
      ["eq", "category", "SWE"],
      ["ilike", "term", "%Fall 2026%"],
      ["gte", "first_seen_at", "2026-10-06T12:00:00.000Z"],
      ["in", "freshness", ["fresh", "recurring"]],
      ["not", "pay_hourly_max", "is", null],
      ["eq", "work_mode", "remote"],
      ["or", 'title.ilike."%data%",company_name.ilike."%data%"'],
      ["order", "pay_hourly_max", { ascending: false, nullsFirst: false }],
      ["order", "first_seen_at", { ascending: false }],
      ["range", 100, 149],
    ]);
  });

  it("only ever puts sanitized text into the or filter", () => {
    const f = parseFilters("us", { q: 'x",id.eq.1),(y' });
    const or = applyFilters(new Recorder(), f, NOW).calls.find((c) => c[0] === "or");
    expect(or).toEqual(["or", 'title.ilike."%x id.eq.1 y%",company_name.ilike."%x id.eq.1 y%"']);
  });
});

describe("termOptions", () => {
  it("extracts season-years in chronological order", () => {
    expect(
      termOptions([
        "Summer 2027",
        "Fall 2026 · 4-month",
        null,
        "8-month",
        "Winter 2027",
        "Summer 2027",
      ]),
    ).toEqual(["Fall 2026", "Winter 2027", "Summer 2027"]);
  });
});
