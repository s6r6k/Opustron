import React, { useState, useEffect } from "react";
import { getEgressLog, MOCK } from "../services/api";

const fmtTs = (ts) =>
  new Date(ts).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

export default function EgressLog() {
  const [entries, setEntries] = useState(MOCK.egressEntries);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const data = await getEgressLog(30);
        if (!cancelled) {
          setEntries(data);
          setError(null);
        }
      } catch {
        // Backend not up yet — keep showing mock data
      }
    };
    poll();
    const id = setInterval(poll, 2000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return (
    <section className="egress-log">
      <header className="egress-header">
        <h2 className="egress-title">Egress Log</h2>
        <span className="egress-subtitle">
          All outbound LLM calls — showing redacted payloads only
        </span>
      </header>

      <div className="egress-entries">
        {entries.length === 0 && (
          <p className="egress-empty">No calls yet.</p>
        )}
        {entries.map((e, i) => (
          <div key={i} className={`egress-entry ${e.redacted ? "egress-redacted" : "egress-clean"}`}>
            <span className="egress-ts">{fmtTs(e.ts)}</span>
            <span className="egress-provider">{e.model.split("/").pop()}</span>
            {e.redacted ? (
              <span className="egress-badge redacted">🔒 redacted</span>
            ) : (
              <span className="egress-badge clean">✓ clean</span>
            )}
            {e.pii_types?.length > 0 && (
              <span className="egress-pii-types">
                {e.pii_types.join(", ")}
              </span>
            )}
            <span className="egress-tokens">
              {e.prompt_tokens}↑ {e.completion_tokens}↓
            </span>
            <code className="egress-preview">{e.request_preview}</code>
          </div>
        ))}
      </div>
    </section>
  );
}
