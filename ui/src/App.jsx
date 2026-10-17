import React, { useState, useEffect } from "react";
import Timeline from "./components/Timeline";
import EntityCard from "./components/EntityCard";
import ChatPanel from "./components/ChatPanel";
import EgressLog from "./components/EgressLog";
import { MOCK, factsAsOf } from "./services/api";
import "./styles.css";

export default function App() {
  const [asOf, setAsOf] = useState(new Date("2026-05-10"));
  const [entities] = useState(MOCK.entities);
  const [allFacts] = useState(MOCK.facts);

  // Facts visible at the current date (for highlighting)
  const currentFacts = factsAsOf(allFacts, asOf.toISOString().slice(0, 10));

  // Unique subjects that have facts
  const subjects = [...new Set(allFacts.map((f) => f.subject))];
  const subjectEntities = subjects.map(
    (name) =>
      entities.find((e) => e.name === name) || {
        entity_id: name,
        name,
        entity_type: "UNKNOWN",
      }
  );

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-logo">
          <span className="app-logo-mark">◈</span>
          <span className="app-title">Chronicle</span>
        </div>
        <span className="app-tagline">A personal agent whose memory keeps up</span>
        <div className="app-header-right">
          <span className="app-corpus-label">Corpus A · Apr–May 2026</span>
        </div>
      </header>

      <div className="app-timeline-section">
        <Timeline
          startDate={MOCK.corpusStart}
          endDate={MOCK.corpusEnd}
          value={asOf}
          onChange={setAsOf}
          facts={allFacts}
        />
      </div>

      <div className="app-body">
        <aside className="app-sidebar">
          <h2 className="sidebar-title">
            Entities
            <span className="sidebar-count">{subjectEntities.length}</span>
          </h2>
          <div className="entity-list">
            {subjectEntities.map((entity) => (
              <EntityCard
                key={entity.entity_id}
                entity={entity}
                allFacts={allFacts}
                asOf={asOf}
              />
            ))}
          </div>
        </aside>

        <main className="app-main">
          <ChatPanel asOf={asOf} />
        </main>
      </div>

      <footer className="app-footer">
        <EgressLog />
      </footer>
    </div>
  );
}
