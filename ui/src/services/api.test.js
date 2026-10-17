import { describe, expect, test } from "vitest";
import { MOCK, allFactsForSubject, factsAsOf } from "./api";

const ids = (facts) => facts.map((f) => f.fact_id).sort();

describe("factsAsOf", () => {
  test("includes both the first and last day of a validity interval", () => {
    expect(ids(factsAsOf(MOCK.facts, "2026-05-01"))).toContain("f1");
    expect(ids(factsAsOf(MOCK.facts, "2026-05-14"))).toContain("f1");
  });

  test("switches the payments owner from Alice to Bob on 15 May", () => {
    const owners = (d) =>
      factsAsOf(MOCK.facts, d)
        .filter((f) => f.subject === "payments service")
        .map((f) => f.object);
    expect(owners("2026-05-14")).toEqual(["Alice Chen"]);
    expect(owners("2026-05-15")).toEqual(["Bob Nakamura"]);
  });

  test("treats a null valid_to as still true", () => {
    expect(ids(factsAsOf(MOCK.facts, "2026-12-31"))).toEqual(["f2", "f3"]);
  });

  test("returns nothing before the corpus starts", () => {
    expect(factsAsOf(MOCK.facts, "2026-04-15")).toEqual([]);
  });
});

test("allFactsForSubject keeps superseded facts", () => {
  expect(ids(allFactsForSubject(MOCK.facts, "payments service"))).toEqual(["f1", "f2"]);
});
