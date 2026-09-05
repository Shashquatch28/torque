import { num, rupees } from "../lib/format.js";
import { Pill } from "./StatusPill.jsx";
import { HeroCounter } from "./HeroCounter.jsx";

// The recovery loop, in money: a connected flow of real amounts, not a
// proportional/stacked chart. Each node is independently labeled — never
// implying an exact sub-total relationship (the four figures are not
// disjoint partitions of one total; a proportional Sankey would overstate
// the precision of that relationship).
function Stage({ cls, k, value, cap }) {
  return (
    <div className={"loop-stage " + cls}>
      <div className="k">{k}</div>
      <div className="v mono">
        <HeroCounter value={value} format={rupees} />
      </div>
      <div className="cap">{cap}</div>
    </div>
  );
}

// A connecting arrow that visibly flows only when there is real amount
// moving through it — an idle/empty pipeline gets a static arrow, not a
// decorative animation running over nothing.
function FlowArrow({ active }) {
  return (
    <div className={"loop-arrow" + (active ? " active" : "")} aria-hidden="true">
      <svg viewBox="0 0 34 16" className="loop-flow">
        <line x1="1" y1="8" x2="24" y2="8" className="loop-flow-line" />
        <polygon points="22,3 32,8 22,13" className="loop-flow-head" />
      </svg>
    </div>
  );
}

export function LoopPipeline({ summary }) {
  const heldBack = Number(summary.blocked_amount || 0) + Number(summary.deferred_amount || 0);
  const stillMoving = Number(summary.unresolved_amount || 0);
  const recovered = Number(summary.recovered_amount || 0);
  return (
    <>
      <div className="loop">
        <Stage cls="risk" k="Revenue at risk" value={summary.revenue_at_risk} cap={`${num(summary.case_count)} cases opened`} />
        <FlowArrow active={Number(summary.case_count || 0) > 0} />
        <Stage cls="hold" k="Held back by guardrails" value={heldBack} cap="compliance-by-construction" />
        <FlowArrow active={stillMoving + recovered > 0} />
        <Stage cls="active" k="Still in motion" value={summary.unresolved_amount} cap={`${num(summary.unresolved_case_count)} cases open`} />
        <FlowArrow active={recovered > 0} />
        <Stage cls="recovered" k="Recovered" value={summary.recovered_amount} cap={`${num(summary.recovered_case_count)} cases closed`} />
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
