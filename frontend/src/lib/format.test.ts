import { describe, expect, it } from "vitest";

import { STATUSES, formatDate, formatSalary } from "./format";

describe("formatSalary", () => {
  it("formats with thousands separator and currency sign", () => {
    expect(formatSalary(250000, "rub")).toBe(`${(250000).toLocaleString("ru-RU")} ₽`);
    expect(formatSalary(5000, "usd")).toMatch(/\$$/);
  });

  it("defaults to rubles and keeps unknown currency code", () => {
    expect(formatSalary(100, null)).toMatch(/₽$/);
    expect(formatSalary(100, "uzs")).toMatch(/uzs$/);
  });

  it("hides missing or zero salary", () => {
    expect(formatSalary(null, "rub")).toBeNull();
    expect(formatSalary(0, "rub")).toBeNull();
  });
});

describe("formatDate", () => {
  it("renders a dash for empty date", () => {
    expect(formatDate(null)).toBe("—");
  });

  it("renders a localized date", () => {
    expect(formatDate("2026-09-30T10:00:00Z")).toMatch(/30/);
  });
});

it("has all four team statuses plus 'new'", () => {
  expect(STATUSES).toEqual(["new", "interesting", "rejected", "contacted", "in_progress"]);
});
