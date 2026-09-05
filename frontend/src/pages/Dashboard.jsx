import { useState } from "react";
import { useMerchant } from "../context/MerchantContext.jsx";
import { useToast } from "../context/ToastContext.jsx";
import { useAsync } from "../lib/useAsync.js";
import { useExplainedCases } from "../lib/useExplainedCases.js";
import { api } from "../lib/api.js";
import { num, pct, pctN, pctSigned, prob, rupees, titleize, friendlyError, STATUS_EDGE } from "../lib/format.js";
import { DashboardSkeleton } from "../components/Skeletons.jsx";
import { HeroCounter } from "../components/HeroCounter.jsx";
import { LoopPipeline } from "../components/LoopPipeline.jsx";
import { LegBars } from "../components/LegBars.jsx";
import { RecoveryOverTimeChart } from "../components/AreaChart.jsx";
import { FeedList, FeedRow } from "../components/FeedRow.jsx";
import { Pill, StatusPill } from "../components/StatusPill.jsx";

function IncrementalityCard({ inc }) {
  const ci = (o) => (o.ci_low == null ? null : `95% CI ${pctSigned(o.ci_low)} … ${pctSigned(o.ci_high)}`);
  const ciRate = (o) => (o.ci_low == null ? null : `95% CI ${pctN(o.ci_low)} … ${pctN(o.ci_high)}`);
  const enough = inc.lift.point != null;
  const s = inc.sutva;
  return (
    <div className="panel mt causal">
      <div className="rowflex">
        <h2>Incrementality — estimated causal effect</h2>
        <Pill tone="blue">causal estimate</Pill>
      </div>
      <p className="faint" style={{ margin: "2px 0 12px" }}>
        The metrics above are <b>descriptive</b> — what happened. This is <b>causal</b> — treatment vs. a held-out control, a
        point estimate with an honest interval. Not proof of causation.
      </p>
      {enough ? (
        <>
          <div className="causal-grid">
            <div className="metric">
              <div className="k">Treatment recovery rate</div>
              <div className="v">{pctN(inc.treatment.rate)}</div>
              <div className="faint">
                {num(inc.treatment.successes)}/{num(inc.treatment.total)} cases{" "}
                {ciRate(inc.treatment) && <span className="ci">{ciRate(inc.treatment)}</span>}
              </div>
            </div>
            <div className="metric">
              <div className="k">Control recovery rate</div>
              <div className="v">{pctN(inc.control.rate)}</div>
              <div className="faint">
                {num(inc.control.successes)}/{num(inc.control.total)} held out{" "}
                {ciRate(inc.control) && <span className="ci">{ciRate(inc.control)}</span>}
              </div>
            </div>
            <div className="metric hl">
              <div className="k">Incremental lift</div>
              <div className="v">{pctSigned(inc.lift.point)}</div>
              <div className="faint">{ci(inc.lift) && <span className="ci">{ci(inc.lift)}</span>}</div>
            </div>
            <div className="metric">
              <div className="k">SUTVA-adjusted lift</div>
              <div className="v">{pctSigned(s.lift.point)}</div>
              <div className="faint">
                {num(s.contaminated_control_counterparties)} contaminated control counterpart
                {s.contaminated_control_counterparties === 1 ? "y" : "ies"} removed{" "}
                {ci(s.lift) && <span className="ci">{ci(s.lift)}</span>}
              </div>
            </div>
          </div>
          <p className="faint mt">{s.note}</p>
          <p className="faint">{inc.recovery_definition}</p>
        </>
      ) : (
        <div className="hatch">
          Not enough cohort data yet — assign a control holdout ({num(inc.treatment.total)} treatment,{" "}
          {num(inc.control.total)} control cases in range).
        </div>
      )}
    </div>
  );
}

export function Dashboard() {
  const { merchantId } = useMerchant();
  const toast = useToast();
  const { explainedCases } = useExplainedCases();
  const [bucket, setBucket] = useState("day");

  const { status, data, error } = useAsync(async () => {
    const m = encodeURIComponent(merchantId);
    const [summary, legs, series, top, exceptions, incrementality] = await Promise.all([
      api(`/reports/${m}/summary`),
      api(`/reports/${m}/by-intervention?by=leg`),
      api(`/reports/${m}/over-time?bucket=${bucket}`),
      api(`/reports/${m}/top-at-risk?limit=8`),
      api(`/reports/${m}/exceptions`),
      api(`/reports/${m}/incrementality`),
    ]);
    return { summary, legs, series, top, exceptions, incrementality };
  }, [merchantId, bucket]);

  if (!merchantId || status === "loading") return <DashboardSkeleton />;
  if (status === "error")
    return (
      <div className="panel">
        <h2>Could not load this page</h2>
        <p className="muted">{friendlyError(error)}</p>
      </div>
    );

  const { summary, legs, series, top, exceptions, incrementality } = data;

  return (
    <>
      <div className="panel hero">
        <div className="label">Revenue recovered by Torque</div>
        <div className="big mono">
          <HeroCounter value={summary.recovered_amount} format={rupees} duration={1200} />
        </div>
        <div className="sub">
          {num(summary.recovered_case_count)} recovered cases &middot; {pct(summary.amount_recovery_rate)} of at-risk revenue
          &middot; self-recovered (not counted): {rupees(summary.self_recovered_amount)}
        </div>
      </div>

      <div className="mt">
        <LoopPipeline summary={summary} />
      </div>

      <div className="grid cols-2 mt">
        <div className="panel">
          <h2>Recovery by leg</h2>
          <LegBars legs={legs} />
        </div>
        <div className="panel">
          <RecoveryOverTimeChart series={series} bucket={bucket} onBucketChange={setBucket} />
        </div>
      </div>

      <IncrementalityCard inc={incrementality} />

      <div className="panel mt">
        <div className="rowflex">
          <h2>Top at-risk cases</h2>
          <span className="faint">ranked by recovery score (backend order)</span>
        </div>
        <FeedList>
          {top.items.map((c) => {
            const notReviewed = c.escalated && !explainedCases.has(c.case_id);
            return (
              <FeedRow
                key={c.case_id}
                to={`/cases/${c.case_id}`}
                edge={STATUS_EDGE[c.status] || ""}
                identity={
                  <>
                    {notReviewed && <span className="aidot" title="AI assessment available, not yet reviewed" />}
                    {c.counterparty_label}
                    {c.escalated && <Pill tone="amber">human</Pill>}
                  </>
                }
                sub={
                  <>
                    {titleize(c.leg_type)} &middot; <StatusPill status={c.status} />
                  </>
                }
                amountLabel="At risk"
                amount={rupees(c.amount_at_risk)}
                meta={
                  <>
                    <div className="score">{prob(c.recovery_probability)} probability</div>
                    <div>{c.next_intervention ? "Next: " + titleize(c.next_intervention) : "Score " + (c.recovery_score == null ? "—" : num(Math.round(c.recovery_score)))}</div>
                  </>
                }
              />
            );
          })}
        </FeedList>
      </div>

      <div className="panel mt">
        <div className="rowflex">
          <h2>Where Torque deliberately held back</h2>
          <span className="faint">compliance-by-construction — not failures</span>
        </div>
        <div className="table-wrap">
          <table className="stackable">
            <thead>
              <tr>
                <th>Guardrail block reason</th>
                <th className="num">Actions</th>
                <th className="num">Cases</th>
                <th className="num">Revenue held</th>
              </tr>
            </thead>
            <tbody>
              {exceptions.blocked_by_reason.length === 0 && exceptions.deferred_action_count === 0 && (
                <tr>
                  <td colSpan={4} className="empty">
                    No blocked actions
                  </td>
                </tr>
              )}
              {exceptions.blocked_by_reason.map((b) => (
                <tr key={b.block_reason}>
                  <td data-label="Reason">
                    <Pill tone="amber">{titleize(b.block_reason)}</Pill>
                  </td>
                  <td className="num" data-label="Actions">
                    {num(b.action_count)}
                  </td>
                  <td className="num" data-label="Cases">
                    {num(b.case_count)}
                  </td>
                  <td className="num" data-label="Revenue held">
                    {rupees(b.revenue_at_risk)}
                  </td>
                </tr>
              ))}
              {exceptions.deferred_action_count > 0 && (
                <tr>
                  <td data-label="Reason">
                    <Pill tone="amber">Outreach Coordinator Deferred</Pill>
                  </td>
                  <td className="num" data-label="Actions">
                    {num(exceptions.deferred_action_count)}
                  </td>
                  <td className="num" data-label="Cases">
                    {num(exceptions.deferred_case_count)}
                  </td>
                  <td className="num faint" data-label="Revenue held">
                    rescheduled
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
