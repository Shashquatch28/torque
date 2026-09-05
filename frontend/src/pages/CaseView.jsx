import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMerchant } from "../context/MerchantContext.jsx";
import { useToast } from "../context/ToastContext.jsx";
import { useAsync } from "../lib/useAsync.js";
import { api } from "../lib/api.js";
import { num, prob, rupeesExact, titleize, when, friendlyError } from "../lib/format.js";
import { CaseViewSkeleton } from "../components/Skeletons.jsx";
import { StatusPill } from "../components/StatusPill.jsx";
import { Gauge } from "../components/Gauge.jsx";
import { Timeline } from "../components/Timeline.jsx";
import { EvidencePanel } from "../components/Evidence.jsx";
import { AiAssessment } from "../components/AiAssessment.jsx";
import { PrecedentCard } from "../components/Precedent.jsx";

const Fact = ({ k, v }) => (
  <div className="fact">
    <div className="k">{k}</div>
    <div className="v">{v}</div>
  </div>
);

// The canonical case screen. One component for both #/cases/:id and the
// #/console/:id alias — everything above the action rail is always visible
// regardless of entry point; the action rail itself is state-gated exactly
// as it always has been (canResolve/canPause/canUnpause). Composition
// mirrors the decision workspace this case represents: what happened -> how
// much is at risk -> why Torque believes recovery is possible -> what the
// AI adds -> what will happen next -> what a human can do -> the full
// trace -> the evidence -> comparable precedent.
export function CaseView({ viaConsole }) {
  const { caseId } = useParams();
  const { merchantId } = useMerchant();
  const navigate = useNavigate();
  const toast = useToast();
  const containerRef = useRef(null);
  const actionRailRef = useRef(null);
  const [narrative, setNarrative] = useState(null);
  const [resolution, setResolution] = useState("RECOVERED_BY_HUMAN");
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);

  const { status, data, error, reload } = useAsync(async () => {
    const m = encodeURIComponent(merchantId);
    const [c, events] = await Promise.all([
      api(`/reports/${m}/cases/${caseId}`),
      api(`/reports/${m}/cases/${caseId}/events`),
    ]);
    return { c, events };
  }, [merchantId, caseId]);

  useEffect(() => {
    setNarrative(null);
  }, [caseId]);

  const canResolveRail = data && data.c.status === "ESCALATED_TO_HUMAN";
  const canPause = data && data.c.status === "PLAYBOOK_ACTIVE";
  const canUnpause = data && data.c.status === "PAUSED";
  const showActionRail = canResolveRail || canPause || canUnpause;

  useEffect(() => {
    if (viaConsole && showActionRail && actionRailRef.current) {
      actionRailRef.current.scrollIntoView({ block: "nearest" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  if (!merchantId || status === "loading") return <CaseViewSkeleton />;
  if (status === "error")
    return (
      <div className="panel">
        <h2>Could not load this case</h2>
        <p className="muted">{friendlyError(error)}</p>
      </div>
    );

  const { c, events } = data;
  const b = c.recovery_score_breakdown;
  const ex = b && b.explain;
  const showNextStep = !c.is_terminal && b && b.next_step_action_type;

  const act = async (path, body) => {
    setBusy(true);
    try {
      const out = await api(`/agent-console/${encodeURIComponent(merchantId)}/cases/${caseId}/${path}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      toast(`${titleize(out.from_status)} → ${titleize(out.to_status)}`);
      await reload();
    } catch (e) {
      toast(friendlyError(e), true);
    }
    setBusy(false);
  };

  return (
    <div ref={containerRef}>
      <a className="back" href={viaConsole ? "#/console" : "#/cases"} onClick={(e) => { e.preventDefault(); navigate(viaConsole ? "/console" : "/cases"); }}>
        &larr; {viaConsole ? "Queue" : "All cases"}
      </a>

      <div className="panel casehead lg mt" id="case-snapshot">
        <div className="idrow">
          <div>
            <div className="who">{c.counterparty_label}</div>
            <div className="cid mono">{c.case_id}</div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <StatusPill status={c.status} />
            {c.recovery_score != null && (
              <div className="gauge-card">
                <Gauge probability={c.recovery_probability} size={88} height={50} />
                <div className="v mono">{prob(c.recovery_probability)}</div>
                <div className="k">Recovery probability</div>
              </div>
            )}
          </div>
        </div>
        <div className="casefacts">
          <Fact k="Leg" v={titleize(c.leg_type)} />
          <Fact k="Revenue at risk" v={rupeesExact(c.revenue_at_risk)} />
          <Fact k="Amount at risk now" v={rupeesExact(c.amount_at_risk)} />
          <Fact k="Root cause" v={c.root_cause_code ? titleize(c.root_cause_code) : "—"} />
          <Fact k="Opened" v={when(c.opened_at)} />
          <Fact k="Attribution" v={c.recovery_type ? titleize(c.recovery_type) : "—"} />
          <Fact k="Recovered" v={c.recovered_amount ? rupeesExact(c.recovered_amount) : "—"} />
          {c.escalation_resolution ? (
            <Fact k="Human resolution" v={`${titleize(c.escalation_resolution)} (${c.escalation_resolved_by || "agent"})`} />
          ) : c.in_human_queue ? (
            <Fact k="Human queue" v={titleize(c.human_queue_reason)} />
          ) : (
            <Fact k="Diagnosis confidence" v={c.diagnosis_confidence == null ? "—" : c.diagnosis_confidence.toFixed(2)} />
          )}
        </div>
      </div>

      {showNextStep && (
        <div className="next-step mt">
          <span className="tag">Next</span>
          <span>
            Torque plans to attempt <b>{titleize(b.next_step_action_type)}</b>
            {b.cost_channels && b.cost_channels.length ? " via " + b.cost_channels[0] : ""} for this case.
          </span>
        </div>
      )}

      <div className="grid cols-2 mt">
        <div className="panel">
          <h2>Why Torque prioritized this case</h2>
          {ex ? (
            <>
              <ul className="signals">
                {(ex.why || []).map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
                {b && b.promise_keeping_rate != null && <li>Customer has kept {prob(b.promise_keeping_rate)} of past payment promises</li>}
              </ul>
              <div className="faint mt" style={{ marginTop: 10 }}>
                Amount at risk {rupeesExact(ex.amount_at_risk)} &middot; expected intervention cost{" "}
                {rupeesExact(ex.expected_cost)} &middot; priority score {num(Math.round(Number(ex.priority_score)))}. probability
                &times; amount &divide; expected cost — computed server-side, rendered verbatim.
              </div>
            </>
          ) : (
            <div className="empty">Not scored yet (terminal or pre-diagnosis case).</div>
          )}
        </div>

        <AiAssessment key={caseId} merchantId={merchantId} caseId={caseId} containerRef={containerRef} onExplained={setNarrative} />
      </div>

      {showActionRail && (
        <div className="panel mt action-rail" ref={actionRailRef}>
          <h2>Actions</h2>
          <div className="btnrow">
            <select aria-label="Resolution" value={resolution} onChange={(e) => setResolution(e.target.value)}>
              <option value="RECOVERED_BY_HUMAN">Resolve — recovered</option>
              <option value="PARTIALLY_RECOVERED_BY_HUMAN">Resolve — partial</option>
              <option value="WRITTEN_OFF">Write off</option>
            </select>
            <input
              type="number"
              placeholder="recovered ₹ (optional)"
              style={{ width: 170 }}
              aria-label="Recovered amount"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
            <button
              className="primary"
              disabled={!canResolveRail || busy}
              onClick={() => act("resolve", { resolution, agent_id: "demo-agent", recovered_amount: amount || null })}
            >
              Resolve
            </button>
            <button disabled={!canPause || busy} onClick={() => act("pause", { agent_id: "demo-agent" })}>
              Pause
            </button>
            <button disabled={!canUnpause || busy} onClick={() => act("unpause", { agent_id: "demo-agent" })}>
              Un-pause
            </button>
          </div>
          <div className="faint" style={{ marginTop: 6 }}>
            Resolve is available only for an escalated case; pause only for one still in a playbook.
          </div>
        </div>
      )}

      <div className="panel mt">
        <h2>Timeline</h2>
        <Timeline events={events} />
      </div>

      <EvidencePanel actions={c.actions || []} />

      <PrecedentCard precedent={narrative && narrative.precedent} containerRef={containerRef} />
    </div>
  );
}
