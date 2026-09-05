import { num, pct, rupees, titleize } from "../lib/format.js";

// Proportional leg bars — replaces a plain leg table with a scannable
// at-risk-vs-recovered comparison across the four legs.
export function LegBars({ legs }) {
  const max = Math.max(...legs.map((l) => Number(l.revenue_at_risk)), 1);
  return (
    <div className="legbars">
      {legs.map((l) => {
        const trackPct = Math.min(100, (Number(l.revenue_at_risk) / max) * 100);
        const fillPct = Math.min(100, (Number(l.recovered_amount) / max) * 100);
        return (
          <div className="legbar-row" key={l.leg_type}>
            <div className="hd">
              <span className="name">{titleize(l.leg_type)}</span>
              <span className="rate">{pct(l.amount_recovery_rate)} recovered</span>
            </div>
            <div className="legbar-track" style={{ width: trackPct + "%" }}>
              <div
                className="legbar-fill"
                style={{ width: `${((fillPct / Math.max(trackPct, 0.01)) * 100).toFixed(1)}%` }}
              />
            </div>
            <div className="meta">
              <span>
                {num(l.cases_recovered)}/{num(l.cases_attempted)} cases recovered
              </span>
              <span>
                {rupees(l.recovered_amount)} of {rupees(l.revenue_at_risk)}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
