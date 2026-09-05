import { STATUS_EDGE, titleize } from "../lib/format.js";

export function StatusPill({ status }) {
  const cls = STATUS_EDGE[status] || "";
  return <span className={"pill " + cls}>{titleize(status)}</span>;
}

export function Pill({ tone, children }) {
  return <span className={"pill " + (tone || "")}>{children}</span>;
}
