import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMerchant } from "../context/MerchantContext.jsx";
import { useAsync } from "../lib/useAsync.js";
import { api } from "../lib/api.js";
import { num, rupees, titleize, when, friendlyError, STATUS_EDGE } from "../lib/format.js";
import { CasesSkeleton } from "../components/Skeletons.jsx";
import { StatusPill, Pill } from "../components/StatusPill.jsx";

const LEGS = ["PAYMENT_DEGRADATION", "CHECKOUT_ABANDONMENT", "SUBSCRIPTION_FAILURE", "B2B_RECEIVABLE"];
const STATUSES = [
  "DETECTED", "DIAGNOSING", "PLAYBOOK_ACTIVE", "ESCALATED_TO_HUMAN",
  "PAUSED", "RECOVERED", "PARTIALLY_RECOVERED", "EXHAUSTED", "CANCELLED", "WRITTEN_OFF",
];
const PAGE_SIZE = 25;

export function Cases() {
  const { merchantId } = useMerchant();
  const navigate = useNavigate();
  const [filter, setFilter] = useState({ leg: "", status: "", offset: 0 });

  const { status, data, error } = useAsync(async () => {
    const m = encodeURIComponent(merchantId);
    const q = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(filter.offset) });
    if (filter.leg) q.set("leg", filter.leg);
    if (filter.status) q.set("status", filter.status);
    return api(`/reports/${m}/cases?` + q.toString());
  }, [merchantId, filter]);

  if (!merchantId || status === "loading") return <CasesSkeleton />;
  if (status === "error")
    return (
      <div className="panel">
        <h2>Could not load this page</h2>
        <p className="muted">{friendlyError(error)}</p>
      </div>
    );

  return (
    <div className="panel">
      <div className="rowflex">
        <h2>Cases — {num(data.total)}</h2>
        <div className="btnrow">
          <select
            aria-label="Filter by leg"
            value={filter.leg}
            onChange={(e) => setFilter((f) => ({ ...f, leg: e.target.value, offset: 0 }))}
          >
            <option value="">All legs</option>
            {LEGS.map((l) => (
              <option key={l} value={l}>
                {titleize(l)}
              </option>
            ))}
          </select>
          <select
            aria-label="Filter by status"
            value={filter.status}
            onChange={(e) => setFilter((f) => ({ ...f, status: e.target.value, offset: 0 }))}
          >
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {titleize(s)}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="table-wrap">
        <table className="stackable">
          <thead>
            <tr>
              <th>Case</th>
              <th>Leg</th>
              <th>Status</th>
              <th className="num">Revenue at risk</th>
              <th>Attribution</th>
              <th className="num">Recovered</th>
              <th>Opened</th>
            </tr>
          </thead>
          <tbody>
            {data.items.length === 0 && (
              <tr>
                <td colSpan={7} className="empty">
                  No cases match
                </td>
              </tr>
            )}
            {data.items.map((c) => (
              <tr
                key={c.case_id}
                className="clickable edge-row"
                tabIndex={0}
                role="button"
                onClick={() => navigate(`/cases/${c.case_id}`)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    navigate(`/cases/${c.case_id}`);
                  }
                }}
              >
                <td className={"edge " + (STATUS_EDGE[c.status] || "")} data-label="Case">
                  <span className="faint mono">{c.case_id.slice(0, 8)}</span>
                </td>
                <td data-label="Leg">{titleize(c.leg_type)}</td>
                <td data-label="Status">
                  <StatusPill status={c.status} />
                </td>
                <td className="num" data-label="Revenue at risk">
                  {rupees(c.revenue_at_risk)}
                </td>
                <td data-label="Attribution">
                  {c.recovery_type ? (
                    <Pill tone={c.recovery_type === "SELF_RECOVERED" ? "blue" : "green"}>{titleize(c.recovery_type)}</Pill>
                  ) : (
                    <span className="faint">—</span>
                  )}
                </td>
                <td className="num" data-label="Recovered">
                  {c.recovered_amount ? rupees(c.recovered_amount) : "—"}
                </td>
                <td className="faint" data-label="Opened">
                  {when(c.opened_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="btnrow mt">
        <button disabled={filter.offset === 0} onClick={() => setFilter((f) => ({ ...f, offset: Math.max(0, f.offset - PAGE_SIZE) }))}>
          &larr; Prev
        </button>
        <button
          disabled={filter.offset + PAGE_SIZE >= data.total}
          onClick={() => setFilter((f) => ({ ...f, offset: f.offset + PAGE_SIZE }))}
        >
          Next &rarr;
        </button>
        <span className="faint" style={{ alignSelf: "center" }}>
          showing {data.items.length ? filter.offset + 1 : 0}–{filter.offset + data.items.length}
        </span>
      </div>
    </div>
  );
}
