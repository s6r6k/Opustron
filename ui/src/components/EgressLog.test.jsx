import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import EgressLog from "./EgressLog";

test("shows mock entries with redacted and clean badges when the backend is down", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
  render(<EgressLog />);
  expect(await screen.findByText("Who owned ORG_1_service on 3 May?")).toBeInTheDocument();
  expect(screen.getByText("🔒 redacted")).toBeInTheDocument();
  expect(screen.getByText("✓ clean")).toBeInTheDocument();
});

test("replaces mock entries with the backend's log", async () => {
  const entries = [
    {
      ts: "2026-10-17T12:00:00Z",
      model: "nvidia/nemotron-mini-4b-instruct",
      prompt_tokens: 10,
      completion_tokens: 3,
      redacted: true,
      request_preview: "When did PERSON_1 join?",
      // pii_types omitted on purpose: the UI must tolerate partial records.
    },
  ];
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => entries }));
  render(<EgressLog />);

  expect(await screen.findByText("When did PERSON_1 join?")).toBeInTheDocument();
  expect(screen.queryByText("Who owned ORG_1_service on 3 May?")).not.toBeInTheDocument();
  expect(fetch).toHaveBeenCalledWith("/api/egress?n=30");
});
