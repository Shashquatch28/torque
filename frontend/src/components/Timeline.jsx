import { rupeesExact, titleize, when } from "../lib/format.js";

function eventBody(e) {
  const p = e.payload || {};
  if (e.reasoning) return <span className="why">{e.reasoning}</span>;
  switch (e.event_type) {
    case "DIAGNOSIS_COMPLETED":
      return (
        <span className="why">
          {titleize(p.root_cause_code)} &middot; confidence {Number(p.diagnosis_confidence).toFixed(2)}
        </span>
      );
    case "ACTION_EXECUTED":
      return (
        <span className="why">
          {titleize(p.action_type)} → {titleize(p.outcome)}
          {p.channel ? " via " + p.channel : ""}
        </span>
      );
    case "ACTION_BLOCKED":
      return (
        <span className="why">
          {titleize(p.action_type)} blocked — {titleize(p.block_reason)}
        </span>
      );
    case "PAYMENT_RECONCILED":
      return (
        <span className="pay">
          {rupeesExact(p.recovered_amount)} recovered ({titleize(p.recovery_type)})
        </span>
      );
    case "STATUS_CHANGED":
      return (
        <span className="why">
          {titleize(p.from_status)} → {titleize(p.to_status)}
        </span>
      );
    case "HUMAN_RESOLVED":
      return (
        <span className="why">
          {titleize(p.resolution)} by {p.agent_id}
        </span>
      );
    default:
      return null;
  }
}

export function Timeline({ events }) {
  if (!events.length) return <div className="empty">No events</div>;
  return (
    <ul className="timeline">
      {events.map((e) => {
        const p = e.payload || {};
        const cls =
          e.event_type === "PAYMENT_RECONCILED" || e.event_type === "HUMAN_RESOLVED"
            ? "ok"
            : e.event_type === "ACTION_BLOCKED"
              ? "block"
              : "";
        return (
          <li
            key={e.event_seq_id}
            className={cls}
            data-event-seq={e.event_seq_id}
            data-action-id={p.action_id || undefined}
            data-promise-id={p.promise_id || undefined}
          >
            <div className="ts">
              {when(e.timestamp)} &middot; #{e.event_seq_id} &middot; {e.actor}
            </div>
            <div className="ev">{titleize(e.event_type)}</div>
            {eventBody(e)}
          </li>
        );
      })}
    </ul>
  );
}
