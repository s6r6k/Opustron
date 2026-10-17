import React, { useMemo } from "react";

const fmt = (d) =>
  d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "2-digit", timeZone: "UTC" });

export default function Timeline({ startDate, endDate, value, onChange, facts = [] }) {
  const totalDays = Math.round((endDate - startDate) / 86400000);
  const currentDay = Math.round((value - startDate) / 86400000);
  const pct = totalDays > 0 ? (currentDay / totalDays) * 100 : 0;

  // Build tick marks at key fact boundaries
  const ticks = useMemo(() => {
    const dates = new Set();
    facts.forEach((f) => {
      if (f.valid_from) dates.add(f.valid_from.slice(0, 10));
      if (f.valid_to) dates.add(f.valid_to.slice(0, 10));
    });
    return [...dates]
      .map((d) => new Date(d))
      .filter((d) => d >= startDate && d <= endDate)
      .map((d) => ({
        date: d,
        pct: ((d - startDate) / (endDate - startDate)) * 100,
        label: fmt(d),
      }));
  }, [facts, startDate, endDate]);

  const handleChange = (e) => {
    const days = Number(e.target.value);
    const date = new Date(startDate.getTime() + days * 86400000);
    onChange(date);
  };

  return (
    <div className="timeline-wrap">
      <div className="timeline-header">
        <span className="timeline-label">Memory Time Machine</span>
        <span className="timeline-date">{fmt(value)}</span>
      </div>

      <div className="timeline-track-wrap">
        <span className="timeline-bound">{fmt(startDate)}</span>
        <div className="timeline-track">
          <div className="timeline-fill" style={{ width: `${pct}%` }} />
          {ticks.map((t) => (
            <div
              key={t.label}
              className="timeline-tick"
              style={{ left: `${t.pct}%` }}
              title={t.label}
            />
          ))}
          <input
            type="range"
            min={0}
            max={totalDays}
            value={currentDay}
            onChange={handleChange}
            className="timeline-slider"
            aria-label="Select date in memory"
          />
        </div>
        <span className="timeline-bound">{fmt(endDate)}</span>
      </div>

      <div className="timeline-facts">
        {facts.map((f) => {
          const from = new Date(f.valid_from);
          const to = f.valid_to ? new Date(f.valid_to) : endDate;
          const isActive = from <= value && value <= to;
          const fromPct = Math.max(0, ((from - startDate) / (endDate - startDate)) * 100);
          const toPct = Math.min(100, ((to - startDate) / (endDate - startDate)) * 100);
          return (
            <div
              key={f.fact_id}
              className={`timeline-fact-bar ${isActive ? "active" : "inactive"}`}
              style={{ left: `${fromPct}%`, width: `${toPct - fromPct}%` }}
              title={`${f.subject} — ${f.predicate}: ${f.object} (${f.valid_from} → ${f.valid_to ?? "now"})`}
            />
          );
        })}
      </div>
    </div>
  );
}
