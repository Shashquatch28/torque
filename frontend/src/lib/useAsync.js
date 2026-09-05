import { useEffect, useRef, useState } from "react";

// A minimal data-fetching hook — deliberately not a library (react-query,
// swr, etc.) at this app's size (five screens, no shared cache needs).
// `fn` is called once per dependency-array change; `reload()` re-runs it.
export function useAsync(fn, deps) {
  const [state, setState] = useState({ status: "loading", data: null, error: null });
  const seq = useRef(0);

  const run = () => {
    const mySeq = ++seq.current;
    setState((s) => ({ ...s, status: "loading" }));
    fn().then(
      (data) => {
        if (mySeq === seq.current) setState({ status: "ok", data, error: null });
      },
      (error) => {
        if (mySeq === seq.current) setState({ status: "error", data: null, error });
      }
    );
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(run, deps);

  return { ...state, reload: run };
}
