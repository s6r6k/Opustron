import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import EntityCard from "./EntityCard";
import { MOCK } from "../services/api";

const payments = MOCK.entities.find((e) => e.name === "payments service");
const row = (name) => screen.getByText(name).closest(".fact-row");

const renderCard = (asOf) => render(<EntityCard entity={payments} allFacts={MOCK.facts} asOf={new Date(asOf)} />);

test("before the handover Alice is current and Bob is not yet true", () => {
  renderCard("2026-05-10");
  expect(row("Alice Chen")).toHaveClass("fact-current");
  expect(row("Bob Nakamura")).not.toHaveClass("fact-current");
  expect(row("Bob Nakamura")).not.toHaveClass("fact-superseded");
});

test("after the handover Alice is struck through and Bob is current", () => {
  renderCard("2026-05-20");
  expect(row("Alice Chen")).toHaveClass("fact-superseded");
  expect(row("Bob Nakamura")).toHaveClass("fact-current");
});

test("validity dates display the stored day, not the day before", () => {
  renderCard("2026-05-20");
  expect(screen.getByText("1 May → 14 May")).toBeInTheDocument();
  expect(screen.getByText("15 May → now")).toBeInTheDocument();
});

test("citation popover opens with the source quote and closes on outside click", async () => {
  renderCard("2026-05-10");
  await userEvent.click(screen.getByRole("button", { name: "Source: email_001" }));
  expect(screen.getByRole("tooltip")).toHaveTextContent("Alice owns the payments service going forward.");

  fireEvent.mouseDown(document.body);
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
});
