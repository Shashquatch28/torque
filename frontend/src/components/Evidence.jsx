import { titleize, when } from "../lib/format.js";
import { Pill } from "./StatusPill.jsx";

// Evidence — Actions taken rendered as a dedicated, scannable list (first-
// class evidence, not folded only into the timeline), grouped so a
// guardrail block reads as its own category. Promises are not shown here:
// CaseDetail exposes no promise list today — the honest choice is to omit
// the section rather than fabricate one from data the API does not return.
function Row({ a }) {
  const outcomeTone =
    a.outcome === "BLOCKED_BY_GUARDRAIL" ? "amber" : a.outcome === "FAILED" || a.outcome === "NO_RESPONSE" ? "red" : "green";
  return (
    <li>
      <div>
        <div className="et">
          {titleize(a.action_type)}
          {a.channel ? " · " + titleize(a.channel) : ""}
        </div>
        <div className="em">
          {a.executed_at ? when(a.executed_at) : "not executed"}
          {a.block_reason ? " · " + titleize(a.block_reason) : ""}
        </div>
      </div>
      <Pill tone={outcomeTone}>{titleize(a.outcome)}</Pill>
    </li>
  );
}

export function EvidencePanel({ actions }) {
  if (!actions.length) {
    return (
      <div className="panel mt">
        <h2>Evidence</h2>
        <div className="empty">No actions recorded yet.</div>
      </div>
    );
  }
  const blocked = actions.filter((a) => a.outcome === "BLOCKED_BY_GUARDRAIL");
  const executed = actions.filter((a) => a.outcome !== "BLOCKED_BY_GUARDRAIL");
  return (
    <div className="panel mt">
      <h2>Evidence</h2>
      {blocked.length > 0 && (
        <div className="evidence-group blocked">
          <div className="gk">Blocked by guardrail</div>
          <ul className="evidence-list">
            {blocked.map((a, i) => (
              <Row a={a} key={i} />
            ))}
          </ul>
        </div>
      )}
      {executed.length > 0 && (
        <div className="evidence-group executed">
          <div className="gk">Executed</div>
          <ul className="evidence-list">
            {executed.map((a, i) => (
              <Row a={a} key={i} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
