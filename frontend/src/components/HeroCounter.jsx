import { useEffect, useRef, useState } from "react";

// Animates a numeric value counting toward `value` whenever it changes,
// formatting every frame with `format` — never itself computes a metric,
// only interpolates one the caller already has. Counts up from 0 on first
// mount; on later updates it animates the delta and (if the value grew)
// applies a brief pulse, so a live re-fetch reads as new activity landing
// rather than a silent number swap.

function easeOutCubic(t) {
  return 1 - Math.pow(1 - t, 3);
}

function prefersReducedMotion() {
  return (
    typeof window !== "undefined" &&
    window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

export function HeroCounter({ value, format = String, duration = 900, className = "" }) {
  const [display, setDisplay] = useState(0);
  const [pulsing, setPulsing] = useState(false);
  const fromRef = useRef(0);
  const mountedRef = useRef(false);

  useEffect(() => {
    const target = Number(value || 0);

    if (prefersReducedMotion()) {
      fromRef.current = target;
      mountedRef.current = true;
      setDisplay(target);
      return;
    }

    const from = fromRef.current;
    const isFirstRun = !mountedRef.current;
    mountedRef.current = true;
    if (from === target) return;

    const grew = target > from && !isFirstRun;
    if (grew) setPulsing(true);

    let raf;
    const start = performance.now();
    function tick(now) {
      const t = Math.min(1, (now - start) / duration);
      setDisplay(from + (target - from) * easeOutCubic(t));
      if (t < 1) {
        raf = requestAnimationFrame(tick);
      } else {
        fromRef.current = target;
      }
    }
    raf = requestAnimationFrame(tick);
    const pulseTimer = grew ? setTimeout(() => setPulsing(false), duration + 200) : null;

    return () => {
      cancelAnimationFrame(raf);
      if (pulseTimer) clearTimeout(pulseTimer);
    };
  }, [value, duration]);

  return (
    <span className={"counter" + (pulsing ? " counter-pulse" : "") + (className ? " " + className : "")}>
      {format(display)}
    </span>
  );
}
