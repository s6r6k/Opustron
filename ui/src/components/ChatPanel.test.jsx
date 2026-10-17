import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import ChatPanel from "./ChatPanel";

const asOf = new Date("2026-05-10");

const answerWith = (body) =>
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => body }));

const askQuestion = async (text) => {
  await userEvent.type(screen.getByRole("textbox"), `${text}{Enter}`);
};

test("header shows the as-of day in UTC", () => {
  render(<ChatPanel asOf={asOf} />);
  expect(screen.getByText("as of 10 May 26")).toBeInTheDocument();
});

test("sends the question with the as-of date", async () => {
  answerWith({ answer: "Alice Chen.", citations: [{ doc_id: "email_001" }] });
  render(<ChatPanel asOf={asOf} />);
  await askQuestion("Who owned payments?");

  expect(await screen.findByText("Alice Chen.")).toBeInTheDocument();
  expect(screen.getByText("email_001")).toBeInTheDocument();
  const [url, init] = fetch.mock.calls[0];
  expect(url).toBe("/api/ask");
  expect(JSON.parse(init.body)).toEqual({ question: "Who owned payments?", as_of: "2026-05-10" });
});

test("falls back to a scaffold reply when the backend is down", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("connection refused")));
  render(<ChatPanel asOf={asOf} />);
  await askQuestion("Who owned payments?");
  expect(await screen.findByText(/Backend not connected/)).toBeInTheDocument();
});

test("renders answer text as text, never as HTML", async () => {
  answerWith({ answer: '<img src=x onerror="window.pwned=1"> owner is **Bob**', citations: [] });
  const { container } = render(<ChatPanel asOf={asOf} />);
  await askQuestion("Who owns payments?");

  expect(await screen.findByText(/owner is/)).toHaveTextContent('<img src=x onerror="window.pwned=1"> owner is Bob');
  expect(container.querySelector("img")).toBeNull();
  expect(screen.getByText("Bob").tagName).toBe("STRONG");
  expect(window.pwned).toBeUndefined();
});

test("Enter on an empty box sends nothing", async () => {
  const fetchSpy = vi.fn();
  vi.stubGlobal("fetch", fetchSpy);
  render(<ChatPanel asOf={asOf} />);
  await askQuestion("   ");
  expect(fetchSpy).not.toHaveBeenCalled();
});
