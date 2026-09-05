import { titleize } from "../lib/format.js";
import { citationLabel, focusCitation } from "../lib/citations.js";
import { useToast } from "../context/ToastContext.jsx";
import { Pill } from "./StatusPill.jsx";

export function PrecedentCard({ precedent, containerRef }) {
  const toast = useToast();
  return (
    <div className="panel mt ai-card" id="precedentCard">
      <h2>
        <span className="aihdr">Similar cases</span>
      </h2>
      {!precedent ? (
        <div className="faint" style={{ marginBottom: 8 }}>
          Generate an AI assessment to surface comparable resolved cases.
        </div>
      ) : !precedent.found || !precedent.cases.length ? (
        <div className="hatch">{precedent.note}</div>
      ) : (
        <div className="table-wrap">
          <table className="stackable">
            <thead>
              <tr>
                <th>Case</th>
                <th>Root cause</th>
                <th>Outcome</th>
                <th>Evidence</th>
              </tr>
            </thead>
            <tbody>
              {precedent.cases.map((pc) => (
                <tr key={pc.case_id}>
                  <td className="faint mono" data-label="Case">
                    {pc.case_id.slice(0, 8)}
                  </td>
                  <td data-label="Root cause">{titleize(pc.root_cause_code)}</td>
                  <td data-label="Outcome">
                    {pc.recovered ? <Pill tone="green">Recovered</Pill> : <Pill>Not recovered</Pill>}{" "}
                    <span className="faint">{pc.outcome_summary}</span>
                  </td>
                  <td data-label="Evidence">
                    <button type="button" className="cite" onClick={() => focusCitation(pc.evidence_id, containerRef.current, toast)}>
                      {citationLabel(pc.evidence_id)}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
