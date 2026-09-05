import { useMemo, useRef, useState } from "react";
import { rupeesExact, titleize } from "../lib/format.js";

// `series` is real backend buckets (one entry per day/week/month that has
// ANY recovered amount, ascending) from /reports/{m}/over-time?bucket= —
// this component never invents a value. With few real buckets a naive
// render reads as one decorative block rather than a trend, so we left-pad
// with explicit zero-recovery periods immediately before the earliest real
// bucket (a period with no recovery genuinely recovered ₹0 — not a
// fabricated number, just the true value for periods the backend has no
// row for) up to a minimum count.
const MIN_BARS = 7;
function padSeries(series, bucket) {
  let padded = series;
  if (padded.length && padded.length < MIN_BARS) {
    const earliest = new Date(padded[0].bucket_start);
    const filler = [];
    for (let i = MIN_BARS - padded.length; i >= 1; i--) {
      const d = new Date(earliest);
      if (bucket === "month") d.setUTCMonth(d.getUTCMonth() - i);
      else if (bucket === "week") d.setUTCDate(d.getUTCDate() - i * 7);
      else d.setUTCDate(d.getUTCDate() - i);
      filler.push({ bucket_start: d.toISOString(), recovered_amount: "0" });
    }
    padded = filler.concat(padded);
  }
  return padded.slice(-24);
}

const W = 640;
const H = 160;

export function RecoveryOverTimeChart({ series, bucket, onBucketChange }) {
  const padded = useMemo(() => padSeries(series, bucket), [series, bucket]);
  const svgRef = useRef(null);
  const [hover, setHover] = useState(null); // index into padded, or null

  const max = Math.max(...padded.map((s) => Number(s.recovered_amount)), 1);
  const n = padded.length;
  const x = (i) => (n === 1 ? W / 2 : (i / (n - 1)) * W);
  const y = (v) => H - 6 - (Number(v) / max) * (H - 12);

  const line = padded
    .map((s, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(s.recovered_amount).toFixed(1)}`)
    .join(" ");
  const area = padded.length
    ? `${line} L${x(n - 1).toFixed(1)},${H} L${x(0).toFixed(1)},${H} Z`
    : "";

  const move = (clientX) => {
    const rect = svgRef.current.getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    setHover(Math.round(frac * (n - 1)));
  };

  const hoveredPoint = hover != null ? padded[hover] : null;

  return (
    <>
      <div className="rowflex">
        <h2>Recovery over time</h2>
        <div className="chart-tabs" role="tablist" aria-label="Time bucket">
          {["day", "week", "month"].map((b) => (
            <button
              key={b}
              type="button"
              role="tab"
              aria-selected={b === bucket}
              className={b === bucket ? "active" : ""}
              onClick={() => onBucketChange(b)}
            >
              {titleize(b)}
            </button>
          ))}
        </div>
      </div>
      {series.length ? (
        <div className="chart-wrap">
          <svg
            ref={svgRef}
            viewBox={`0 0 ${W} ${H}`}
            preserveAspectRatio="none"
            role="img"
            aria-label="Recovered amount over time"
            onPointerMove={(e) => move(e.clientX)}
            onPointerDown={(e) => move(e.clientX)}
            onPointerLeave={() => setHover(null)}
          >
            <defs>
              <linearGradient id="areafill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--green)" stopOpacity=".35" />
                <stop offset="100%" stopColor="var(--green)" stopOpacity="0" />
              </linearGradient>
            </defs>
            <path d={area} fill="url(#areafill)" stroke="none" />
            <path d={line} fill="none" stroke="var(--green)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
            {hoveredPoint && (
              <>
                <line
                  className="chart-guide"
                  style={{ opacity: 1 }}
                  x1={x(hover)}
                  x2={x(hover)}
                  y1={0}
                  y2={H}
                />
                <circle className="chart-dot" style={{ opacity: 1 }} r="4" cx={x(hover)} cy={y(hoveredPoint.recovered_amount)} />
              </>
            )}
          </svg>
          {hoveredPoint && (
            <div
              className="chart-tip show"
              style={{ left: `${(x(hover) / W) * 100}%`, top: `${(y(hoveredPoint.recovered_amount) / H) * 100}%` }}
            >
              <span className="date">{new Date(hoveredPoint.bucket_start).toDateString()}</span>
              <br />
              <span className="amt">{rupeesExact(hoveredPoint.recovered_amount)}</span>
            </div>
          )}
        </div>
      ) : (
        <div className="hatch">No recoveries in range yet</div>
      )}
      <div className="faint" style={{ marginTop: 8 }}>
        Torque-credited recoveries, by {bucket} (UTC). Hover to inspect a point.
      </div>
    </>
  );
}
