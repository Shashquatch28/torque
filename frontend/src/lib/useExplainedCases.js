import { useState } from "react";

const KEY = "torque.explained";

// A frontend-only, no-new-field convention: cases this browser has already
// generated an AI explanation for in this session are remembered so the
// dashboard's "AI available, not yet reviewed" dot only lights up for cases
// that genuinely have not been looked at yet in this session.
export function useExplainedCases() {
  const [set, setSet] = useState(() => new Set(JSON.parse(sessionStorage.getItem(KEY) || "[]")));

  const markExplained = (caseId) => {
    setSet((prev) => {
      const next = new Set(prev);
      next.add(caseId);
      sessionStorage.setItem(KEY, JSON.stringify([...next]));
      return next;
    });
  };

  return { explainedCases: set, markExplained };
}
