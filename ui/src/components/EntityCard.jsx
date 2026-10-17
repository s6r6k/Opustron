import React, { useState } from "react";
import CitationPopover from "./CitationPopover";
import { allFactsForSubject } from "../services/api";

const fmt = (d) =>
  d
    ? new Date(d).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" })
    : "now";

export default function EntityCard({ entity, allFacts, asOf }) {
  const [openCitation, setOpenCitation] = useState(null);

  const subjectFacts = allFactsForSubject(allFacts, entity.name);
  const asOfDate = new Date(asOf);

  // Group facts by predicate
  const byPredicate = {};
  subjectFacts.forEach((f) => {
    if (!byPredicate[f.predicate]) byPredicate[f.predicate] = [];
    byPredicate[f.predicate].push(f);
  });

  return (
    <article className="entity-card">
      <header className="entity-card-header">
        <span className="entity-type-badge">{entity.entity_type}</span>
        <h3 className="entity-name">{entity.name}</h3>
      </header>

      <div className="entity-facts">
        {Object.entries(byPredicate).map(([predicate, facts]) => {
          const sorted = [...facts].sort(
            (a, b) => new Date(a.valid_from) - new Date(b.valid_from)
          );
          return (
            <div key={predicate} className="entity-predicate-group">
              <span className="entity-predicate">{predicate}</span>
              <div className="entity-values">
                {sorted.map((f) => {
                  const from = new Date(f.valid_from);
                  const to = f.valid_to ? new Date(f.valid_to) : null;
                  const isCurrent = from <= asOfDate && (to === null || asOfDate <= to);
                  const isSuperseded = to !== null && asOfDate > to;

                  return (
                    <div
                      key={f.fact_id}
                      className={`fact-row ${isCurrent ? "fact-current" : ""} ${isSuperseded ? "fact-superseded" : ""}`}
                    >
                      <span className="fact-object">{f.object}</span>
                      <span className="fact-validity">
                        {fmt(f.valid_from)} → {fmt(f.valid_to)}
                      </span>
                      <button
                        className="citation-btn"
                        onClick={() =>
                          setOpenCitation(openCitation === f.fact_id ? null : f.fact_id)
                        }
                        aria-label={`Source: ${f.doc_id}`}
                      >
                        {f.doc_id}
                      </button>
                      {openCitation === f.fact_id && (
                        <CitationPopover
                          source={{ uri: f.doc_id, quote: f.quote }}
                          onClose={() => setOpenCitation(null)}
                        />
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </article>
  );
}
