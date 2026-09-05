import { useNavigate } from "react-router-dom";

// A priority feed row — used for both the dashboard's top-at-risk list and
// the Agent Console's human queue. A triage feed, not a spreadsheet: one
// glance gives identity, why it matters economically, and where it stands.
export function FeedRow({ to, edge, identity, sub, amountLabel, amount, meta }) {
  const navigate = useNavigate();
  const go = () => navigate(to);
  return (
    <div
      className={"feed-row " + (edge || "")}
      tabIndex={0}
      role="button"
      onClick={go}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          go();
        }
      }}
    >
      <div className="identity">
        <div className="name">{identity}</div>
        <div className="sub">{sub}</div>
      </div>
      <div className="amt">
        <div className="v mono">{amount}</div>
        <div className="k">{amountLabel}</div>
      </div>
      <div className="meta">{meta}</div>
    </div>
  );
}

export function FeedList({ children }) {
  return <div className="feedlist">{children || <div className="empty">Nothing here right now</div>}</div>;
}
