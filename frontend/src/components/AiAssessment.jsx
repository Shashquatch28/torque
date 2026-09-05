import { useState } from "react";
import { api } from "../lib/api.js";
import { when } from "../lib/format.js";
import { citationLabel, focusCitation } from "../lib/citations.js";
import { useToast } from "../context/ToastContext.jsx";
import { AiLoading } from "./Skeletons.jsx";

// Read-only decision support: a citation-grounded narrative fetched only on
// request (never on page load, never polled), rendered from the
// CaseNarrative schema as-is — no parallel frontend representation, no chat
// UI. Every citation resolves back to a row already shown in the case view
// above it.

function CiteGroup({ ids, containerRef }) {
  const toast = useToast();
  if (!ids || !ids.length) return <span className="faint">(no citation)</span>;
  return ids.map((id) => (
    <button
      type="button"
      className="cite"
      key={id}
      onClick={() => focusCitation(id, containerRef.current, toast)}
    >
      {citationLabel(id)}
    </button>
  ));
}

function ClaimLine({ claim, containerRef }) {
  return (
    <p className="claim">
      {claim.claim} <CiteGroup ids={claim.citation_ids} containerRef={containerRef} />
    </p>
  );
}

function ClaimList({ items, containerRef }) {
  if (!items.length) return <div className="faint">None recorded.</div>;
  return (
    <ul className="claims">
      {items.map((nc, i) => (
        <li key={i}>
          {nc.claim} <CiteGroup ids={nc.citation_ids} containerRef={containerRef} />
        </li>
      ))}
    </ul>
  );
}

function Narrative({ n, containerRef }) {
  return (
    <div className="ai-narrative">
      <p className="ai-summary">{n.summary}</p>
      <div className="ai-block">
        <div className="ai-k">Current state</div>
        <ClaimLine claim={n.current_state} containerRef={containerRef} />
      </div>
      <div className="ai-block">
        <div className="ai-k">Root cause</div>
        <ClaimLine claim={n.root_cause_explanation} containerRef={containerRef} />
      </div>
      <div className="ai-block">
        <div className="ai-k">Timeline</div>
        <ClaimList items={n.timeline} containerRef={containerRef} />
      </div>
      <div className="ai-block">
        <div className="ai-k">Actions taken</div>
        <ClaimList items={n.actions_taken} containerRef={containerRef} />
      </div>
      {n.guardrail_explanation.length > 0 && (
        <div className="ai-block">
          <div className="ai-k">Guardrails</div>
          <ClaimList items={n.guardrail_explanation} containerRef={containerRef} />
        </div>
      )}
      {n.recommended_human_attention && (
        <div className="ai-block">
          <div className="ai-k">Worth a second look</div>
          <div className="ai-callout">{n.recommended_human_attention}</div>
        </div>
      )}
      <div className="ai-block">
        <div className="ai-k">Uncertainty</div>
        <p className="faint">{n.uncertainty}</p>
      </div>
      {n.evidence_gaps.length > 0 && (
        <div className="ai-block">
          <div className="ai-k">What Torque doesn't know yet</div>
          <ul className="why-lines">
            {n.evidence_gaps.map((g, i) => (
              <li key={i}>{g}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="faint ai-meta">
        Generated {when(n.generated_at)} &middot; {n.provider_id} &middot; {n.prompt_version}
      </div>
    </div>
  );
}

export function AiAssessment({ merchantId, caseId, containerRef, onExplained }) {
  const [state, setState] = useState({ status: "idle" }); // idle | loading | ok | error
  const toast = useToast();

  const explain = async () => {
    setState({ status: "loading" });
    try {
      const n = await api(`/ai/${encodeURIComponent(merchantId)}/cases/${caseId}/explain`);
      setState({ status: "ok", narrative: n });
      onExplained(n);
    } catch (e) {
      let msg = "Could not generate an explanation right now.";
      if (e.status === 503) msg = "AI explanations are not enabled for this deployment.";
      else if (e.status === 404) msg = "This case could not be found.";
      else if (e.status >= 500) msg = "The AI explanation could not be generated for this case.";
      setState({ status: "error", msg });
    }
  };

  return (
    <div className="panel ai-card" id="aiCard">
      <div className="rowflex">
        <h2>
          <span className="aihdr">AI Assessment</span>
        </h2>
      </div>
      <p className="ai-intro">Torque's AI reads this case's evidence and explains it. It never changes anything.</p>
      <button type="button" className="ai" id="doExplain" onClick={explain} disabled={state.status === "loading"}>
        Explain this case
      </button>
      <div id="aiPanel">
        {state.status === "loading" && <AiLoading />}
        {state.status === "ok" && <Narrative n={state.narrative} containerRef={containerRef} />}
        {state.status === "error" && <div className="ai-error">{state.msg}</div>}
      </div>
    </div>
  );
}
