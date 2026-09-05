import { useMerchant } from "../context/MerchantContext.jsx";
import { useAsync } from "../lib/useAsync.js";
import { api } from "../lib/api.js";
import { num, rupees, titleize, friendlyError } from "../lib/format.js";
import { ConsoleSkeleton } from "../components/Skeletons.jsx";
import { FeedList, FeedRow } from "../components/FeedRow.jsx";
import { StatusPill, Pill } from "../components/StatusPill.jsx";

export function Console() {
  const { merchantId } = useMerchant();
  const { status, data, error } = useAsync(async () => {
    return api(`/reports/${encodeURIComponent(merchantId)}/human-queue`);
  }, [merchantId]);

  if (!merchantId || status === "loading") return <ConsoleSkeleton />;
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
        <h2>Human queue — {data.items.length}</h2>
        <span className="faint">ordered by economic priority</span>
      </div>
      <FeedList>
        {data.items.map((q) => (
          <FeedRow
            key={q.case_id}
            to={`/console/${q.case_id}`}
            edge="amber"
            identity={q.counterparty_label}
            sub={
              <>
                {titleize(q.leg_type)} &middot; <StatusPill status={q.status} />
              </>
            }
            amountLabel="At risk"
            amount={rupees(q.amount_at_risk)}
            meta={
              <>
                <div>
                  <Pill tone="amber">{titleize(q.reason)}</Pill>
                </div>
                <div>Priority {num(Math.round(q.priority))}</div>
              </>
            }
          />
        ))}
      </FeedList>
    </div>
  );
}
