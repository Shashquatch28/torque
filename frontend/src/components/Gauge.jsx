// A single semi-circular gauge — used sparingly (the case header's recovery
// probability), never as a dashboard-wide pattern. Pure inline SVG, no
// charting library.
export function Gauge({ probability, size, height }) {
  if (probability == null) return null;
  const frac = Math.max(0, Math.min(1, Number(probability)));
  const W = size || 64;
  const H = height || 36;
  const r = 26;
  const c = Math.PI * r; // half-circumference (semicircle)
  const dash = c * frac;
  return (
    <svg className="ring" width={W} height={H} viewBox="0 0 64 36" aria-hidden="true">
      <path
        d="M 4 34 A 28 28 0 0 1 60 34"
        fill="none"
        stroke="var(--line)"
        strokeWidth="6"
        strokeLinecap="round"
      />
      <path
        d="M 4 34 A 28 28 0 0 1 60 34"
        fill="none"
        stroke="var(--blue)"
        strokeWidth="6"
        strokeLinecap="round"
        strokeDasharray={`${dash.toFixed(1)} ${c.toFixed(1)}`}
      />
    </svg>
  );
}
