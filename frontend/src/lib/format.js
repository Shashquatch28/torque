// Presentation-only formatting helpers. None of these compute a metric,
// score, or ranking — every number they touch already came from the API.

export function rupees(v) {
  const n = Number(v || 0);
  if (n >= 1e7) return "₹" + (n / 1e7).toFixed(2) + " Cr";
  if (n >= 1e5) return "₹" + (n / 1e5).toFixed(2) + " L";
  return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

export const rupeesExact = (v) =>
  "₹" + Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 2 });

export const pct = (v) => (Number(v || 0) * 100).toFixed(1) + "%";

// null-safe percent, and a signed percent for a lift that can be < 0.
export const pctN = (v) => (v == null ? "—" : (Number(v) * 100).toFixed(1) + "%");
export const pctSigned = (v) =>
  v == null ? "—" : (Number(v) >= 0 ? "+" : "") + (Number(v) * 100).toFixed(1) + "%";
export const prob = (v) => (v == null ? "—" : Math.round(Number(v) * 100) + "%");
export const num = (v) => Number(v || 0).toLocaleString("en-IN");

export const titleize = (s) =>
  String(s || "")
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());

export const when = (s) =>
  s
    ? new Date(s).toLocaleString("en-IN", { hour12: false, dateStyle: "medium", timeStyle: "short" })
    : "—";

export const STATUS_EDGE = {
  RECOVERED: "green",
  PARTIALLY_RECOVERED: "green",
  CANCELLED: "blue",
  ESCALATED_TO_HUMAN: "amber",
  EXHAUSTED: "red",
  WRITTEN_OFF: "red",
  PAUSED: "amber",
};

// Human-readable errors everywhere — never a raw Error.message/stack.
export function friendlyError(e) {
  if (e && e.status === 404) return "This could not be found.";
  if (e && e.status === 503) return "This feature is not enabled for this deployment.";
  if (e && e.status >= 500) return "Something went wrong loading this. Please try again.";
  if (e && e.status === 409) return "That action is no longer available for this case.";
  if (e && e.status === 422) return "That request could not be understood.";
  return "Something went wrong loading this. Please try again.";
}
