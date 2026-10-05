import { describe, expect, it } from "vitest";
import { isPreset, rangeSpanMs, timeRangeLabel, timeRangeParams, validateCustomRange } from "./timeRange";

describe("time ranges", () => {
  it("recognises presets", () => {
    expect(isPreset("30m")).toBe(true);
    expect(isPreset("custom")).toBe(true);
    expect(isPreset("2h")).toBe(false);
    expect(isPreset(null)).toBe(false);
  });

  it("builds backend parameters", () => {
    expect(timeRangeParams({ preset: "6h" })).toEqual({ timeRange: "6h" });
    expect(
      timeRangeParams({ preset: "custom", start: "2026-09-01T00:00:00Z", end: "2026-09-02T00:00:00Z" }),
    ).toEqual({ timeRange: "custom", start: "2026-09-01T00:00:00.000Z", end: "2026-09-02T00:00:00.000Z" });
    // An incomplete custom range falls back to a safe preset.
    expect(timeRangeParams({ preset: "custom" })).toEqual({ timeRange: "24h" });
  });

  it("computes spans", () => {
    expect(rangeSpanMs({ preset: "1h" })).toBe(3600_000);
    expect(rangeSpanMs({ preset: "custom", start: "2026-09-01T00:00:00Z", end: "2026-09-01T02:00:00Z" })).toBe(7200_000);
  });

  it("labels presets", () => {
    expect(timeRangeLabel({ preset: "7d" })).toBe("Last 7 days");
  });

  it("validates custom ranges", () => {
    expect(validateCustomRange(undefined, "2026-09-01T00:00")).toMatch(/both/);
    expect(validateCustomRange("2026-09-02T00:00", "2026-09-01T00:00")).toMatch(/after/);
    expect(validateCustomRange("2026-01-01T00:00", "2026-09-01T00:00")).toMatch(/93 days/);
    expect(validateCustomRange("2026-09-01T00:00", "2026-09-02T00:00")).toBeNull();
  });
});
