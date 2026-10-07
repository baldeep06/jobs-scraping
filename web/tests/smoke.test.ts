import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("design tokens", () => {
  const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
  it.each([
    ["--color-signal", "#1b55f5"],
    ["--color-canvas", "#f4f4f6"],
    ["--color-graphite", "#454554"],
    ["--radius-card", "24px"],
  ])("defines %s = %s", (token, value) => {
    expect(css).toContain(`${token}: ${value}`);
  });
});
