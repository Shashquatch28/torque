import { num, rupees } from "../lib/format.js";
import { Pill } from "./StatusPill.jsx";

// The recovery loop, in money: a connected flow of real amounts, not a
// proportional/stacked chart. Each node is independently labeled — never
// implying an exact sub-total relationship (the four figures are not
// disjoint partitions of one total; a proportional Sankey would overstate
// the precision of that relationship).
function Stage({ cls, k, v, cap }) {
  return (
    <div className={"loop-stage " + cls}>
      <div className="k">{k}</div>
      <div className="v mono">{v}</div>
      <div className="cap">{cap}</div>
    </div>
  );
}

export function LoopPipeline({ summary }) {
  const heldBack = Number(summary.blocked_amount || 0) + Number(summary.deferred_amount || 0);
  return (
    <>
      <div className="loop">
        <Stage cls="risk" k="Revenue at risk" v={rupees(summary.revenue_at_risk)} cap={`${num(summary.case_count)} cases opened`} />
        <div className="loop-arrow" aria-hidden="true">
          &rarr;
        </div>
        <Stage cls="hold" k="Held back by guardrails" v={rupees(heldBack)} cap="compliance-by-construction" />
        <div className="loop-arrow" aria-hidden="true">
          &rarr;
        </div>
        <Stage cls="active" k="Still in motion" v={rupees(summary.unresolved_amount)} cap={`${num(summary.unresolved_case_count)} cases open`} />
        <div className="loop-arrow" aria-hidden="true">
          &rarr;
        </div>
        <Stage cls="recovered" k="Recovered" v={rupees(summary.recovered_amount)} cap={`${num(summary.recovered_case_count)} cases closed`} />
      </div>
      {summary.escalated_case_count > 0 && (
        <div className="loop-note">
          <Pill tone="amber">human</Pill>
          {num(summary.escalated_case_count)} case{summary.escalated_case_count === 1 ? "" : "s"} escalated to a human
          reviewer — restraint, not failure
        </div>
      )}
    </>
  );
}
