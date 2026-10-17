import { expect, test } from "vitest";

// The date-display tests below only prove anything if they run west of UTC.
test("tests run in a timezone west of UTC", () => {
  expect(Intl.DateTimeFormat().resolvedOptions().timeZone).toBe("America/Los_Angeles");
  expect(new Date("2026-05-10").getDate()).toBe(9);
});
