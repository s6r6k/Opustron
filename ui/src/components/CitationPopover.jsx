import React, { useEffect, useRef } from "react";

export default function CitationPopover({ source, onClose }) {
  const ref = useRef(null);

  useEffect(() => {
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) onClose();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onClose]);

  return (
    <div className="citation-popover" ref={ref} role="tooltip">
      <button className="citation-close" onClick={onClose} aria-label="Close">
        ×
      </button>
      <p className="citation-doc">
        <strong>Source:</strong> {source?.uri || source?.title}
      </p>
      {source?.quote && (
        <blockquote className="citation-quote">"{source.quote}"</blockquote>
      )}
    </div>
  );
}
