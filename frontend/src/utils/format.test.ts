import { describe, expect, it } from "vitest";
import { formatBytes, formatDateTime, formatRelative, formatValue, regionName, slugify } from "./format";

describe("formatValue", () => {
  it("formats percentages", () => {
    expect(formatValue(42.3, "percent")).toBe("42%");
    expect(formatValue(4.25, "percent")).toBe("4.3%");
    expect(formatValue(0.2, "percent")).toBe("0.20%");
  });

  it("formats durations", () => {
    expect(formatValue(142, "milliseconds")).toBe("142 ms");
    expect(formatValue(1.5, "seconds")).toBe("1.50 s");
  });

  it("formats bytes and throughput", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatValue(1536, "bytes")).toBe("1.5 KB");
    expect(formatValue(1048576, "bytes_per_second")).toBe("1.0 MB/s");
  });

  it("uses compact notation for large counts", () => {
    expect(formatValue(12481, "count")).toBe("12.5K");
    expect(formatValue(812, "count")).toBe("812");
  });

  it("shows a dash for missing values", () => {
    expect(formatValue(null, "percent")).toBe("-");
    expect(formatValue(undefined, "count")).toBe("-");
  });
});

describe("dates", () => {
  it("formats DD/MM/YYYY HH:mm", () => {
    const local = new Date(2026, 8, 30, 14, 5);
    expect(formatDateTime(local)).toBe("30/09/2026 14:05");
    expect(formatDateTime(null)).toBe("-");
  });

  it("formats relative times", () => {
    const now = new Date("2026-09-30T12:00:00Z");
    expect(formatRelative("2026-09-30T11:59:50Z", now)).toBe("just now");
    expect(formatRelative("2026-09-30T11:50:00Z", now)).toBe("10 minutes ago");
    expect(formatRelative("2026-09-30T09:00:00Z", now)).toBe("3 hours ago");
    expect(formatRelative(null, now)).toBe("never");
  });
});

describe("misc", () => {
  it("slugifies names", () => {
    expect(slugify("  CRM Platform (EU) ")).toBe("crm-platform-eu");
  });

  it("maps region names", () => {
    expect(regionName("uksouth")).toBe("UK South");
    expect(regionName("brazilsouth")).toBe("brazilsouth");
  });
});
