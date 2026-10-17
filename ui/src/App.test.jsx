import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import App from "./App";

test("dragging the time machine changes who owns payments", () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
  const { container } = render(<App />);
  const paymentsRow = (name) =>
    screen
      .getAllByText(name)
      .map((el) => el.closest(".fact-row"))
      .find((r) => r?.closest(".entity-card").textContent.includes("payments service"));

  expect(paymentsRow("Alice Chen")).toHaveClass("fact-current");

  fireEvent.change(screen.getByLabelText("Select date in memory"), { target: { value: "34" } }); // 20 May
  expect(container.querySelector(".timeline-date")).toHaveTextContent("20 May 26");
  expect(screen.getByText("as of 20 May 26")).toBeInTheDocument();
  expect(paymentsRow("Alice Chen")).toHaveClass("fact-superseded");
  expect(paymentsRow("Bob Nakamura")).toHaveClass("fact-current");
});
