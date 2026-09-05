import { useEffect, useRef, useState } from "react";
import { useMerchant } from "../context/MerchantContext.jsx";
import { useToast } from "../context/ToastContext.jsx";
import { useAsync } from "../lib/useAsync.js";
import { api } from "../lib/api.js";
import { titleize, friendlyError } from "../lib/format.js";
import { DemoSkeleton } from "../components/Skeletons.jsx";
import { Pill } from "../components/StatusPill.jsx";

export function Demo() {
  const { merchantId } = useMerchant();
  const toast = useToast();
  const [feed, setFeed] = useState([]);
  const [busyKey, setBusyKey] = useState(null);
  const [seeding, setSeeding] = useState(false);
  const lastSeq = useRef(0);
  const pollTimer = useRef(null);

  const { status, data, error, reload } = useAsync(async () => {
    const [scenarios, dm] = await Promise.all([api("/demo/scenarios"), api("/demo/merchant")]);
    return { scenarios, dm };
  }, [merchantId]);

  const pollFeed = async (force) => {
    if (!merchantId) return;
    let f;
    try {
      f = await api(`/reports/${encodeURIComponent(merchantId)}/activity?limit=40`);
    } catch (e) {
      return;
    }
    const items = f.items;
    const maxSeq = items.length ? items[0].event_seq_id : 0;
    if (!force && maxSeq === lastSeq.current) return;
    lastSeq.current = maxSeq;
    setFeed(items);
  };

  useEffect(() => {
    if (status !== "ok") return;
    pollFeed(true);
    pollTimer.current = setInterval(() => pollFeed(false), 3000);
    return () => clearInterval(pollTimer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, merchantId]);

  if (!merchantId || status === "loading") return <DemoSkeleton />;
  if (status === "error")
    return (
      <div className="panel">
        <h2>Could not load this page</h2>
        <p className="muted">{friendlyError(error)}</p>
      </div>
    );

  const { scenarios, dm } = data;

  const inject = async (key) => {
    setBusyKey(key);
    try {
      const out = await api(`/demo/inject/${key}`, { method: "POST" });
      toast(`Injected — case ${out.case_id.slice(0, 8)} ${out.block_reason ? "blocked (" + titleize(out.block_reason) + ")" : "created"}`);
      await pollFeed(true);
    } catch (e) {
      toast(friendlyError(e), true);
    }
    setBusyKey(null);
  };

  const seed = async () => {
    setSeeding(true);
    try {
      const r = await api("/demo/seed?reset=true", { method: "POST" });
      toast(`Seeded — ${r.case_count} cases`);
      await reload();
      await pollFeed(true);
    } catch (e) {
      toast(friendlyError(e), true);
    }
    setSeeding(false);
  };

  return (
    <div className="grid cols-2">
      <div className="panel">
        <h2>Inject a synthetic event</h2>
        <div className="faint">Each button runs the real ingestion / compliance code — no fake data.</div>
        <div className="grid mt" style={{ gap: 8 }}>
          {scenarios.map((s) => (
            <button key={s.key} className="scenario" disabled={busyKey === s.key} onClick={() => inject(s.key)}>
              <span className="lbl">
                {s.label} <Pill tone={s.kind === "restraint" ? "amber" : "green"}>{s.kind === "restraint" ? "restraint" : "acts"}</Pill>
              </span>
              <span className="desc">{s.description}</span>
            </button>
          ))}
        </div>
        <div className="btnrow mt">
          <button disabled={seeding} onClick={seed}>
            {dm.seeded ? "Re-seed demo data" : "Seed demo data"}
          </button>
          <a className="btn" href="#/dashboard">
            Open dashboard &rarr;
          </a>
        </div>
      </div>
      <div className="panel">
        <div className="rowflex">
          <h2>Live feed</h2>
          <span className="faint">polling every 3s…</span>
        </div>
        <ul className="feed" aria-live="polite">
          {feed.length === 0 && <li className="empty">Waiting for events…</li>}
          {feed.map((e, i) => (
            <li key={e.event_seq_id} className={i < 3 ? "fresh" : ""}>
              <span className="seq">#{e.event_seq_id}</span>
              <span className="body">
                <span className="et">{titleize(e.event_type)}</span>
                <span className="faint"> &middot; {titleize(e.leg_type)} &middot; {titleize(e.case_status)}</span>
                <div className="faint">{e.reasoning || ""}</div>
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
