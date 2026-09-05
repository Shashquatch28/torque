// A citation id is only ever `source_type:source_id` from the AI schema's
// own scheme (torque.ai.schemas.EvidenceReference.reference_id). Anchoring
// resolves it against real on-screen elements the case view already
// rendered — never a second, parallel representation of the evidence.

export function citationLabel(id) {
  const [type, ref] = String(id).split(":");
  const names = {
    case: "Case snapshot",
    case_event: `Event ${ref}`,
    action: `Action ${String(ref || "").slice(0, 8)}`,
    promise: `Promise ${String(ref || "").slice(0, 8)}`,
    counterparty_relationship: "Customer relationship",
  };
  return names[type] || String(id);
}

function cssEscape(s) {
  if (window.CSS && CSS.escape) return CSS.escape(s);
  return String(s).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
}

function flashElement(el) {
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add("cite-hit");
  setTimeout(() => el.classList.remove("cite-hit"), 1600);
}

// `root` is the scrollable case-view container to search within (a ref's
// .current), so a citation never resolves outside the case actually shown.
export function focusCitation(id, root, toast) {
  const s = String(id);
  const scope = root || document;
  let m = /^case_event:(\d+)$/.exec(s);
  if (m) {
    const li = scope.querySelector(`li[data-event-seq="${m[1]}"]`);
    if (!li) return toast(`Event #${m[1]} is not shown in this view`);
    return flashElement(li);
  }
  m = /^action:([0-9a-fA-F-]+)$/.exec(s);
  if (m) {
    const li = scope.querySelector(`li[data-action-id="${cssEscape(m[1])}"]`);
    if (!li) return toast("Referenced: " + citationLabel(id));
    return flashElement(li);
  }
  m = /^promise:([0-9a-fA-F-]+)$/.exec(s);
  if (m) {
    const li = scope.querySelector(`li[data-promise-id="${cssEscape(m[1])}"]`);
    if (!li) return toast("Referenced: " + citationLabel(id));
    return flashElement(li);
  }
  if (/^case:/.test(s)) {
    const el = scope.querySelector("#case-snapshot");
    if (!el) return toast("Referenced: " + citationLabel(id));
    el.classList.add("case-anchor");
    return flashElement(el);
  }
  if (/^counterparty_relationship:/.test(s)) {
    return toast("Customer relationship — not shown in this view");
  }
  toast("Referenced: " + citationLabel(id));
}
