import { Navigate, Route, HashRouter, Routes } from "react-router-dom";
import { MerchantProvider } from "./context/MerchantContext.jsx";
import { ToastProvider } from "./context/ToastContext.jsx";
import { AppShell } from "./components/AppShell.jsx";
import { Dashboard } from "./pages/Dashboard.jsx";
import { Cases } from "./pages/Cases.jsx";
import { CaseView } from "./pages/CaseView.jsx";
import { Console } from "./pages/Console.jsx";
import { Demo } from "./pages/Demo.jsx";

// Hash routing (#/dashboard, #/cases/:id, #/console/:id, #/demo) — the same
// URL scheme the previous static frontend used, so existing bookmarks/links
// and the backend's zero-knowledge-of-frontend-routes contract are both
// preserved unchanged.
export function App() {
  return (
    <ToastProvider>
      <MerchantProvider>
        <HashRouter>
          <Routes>
            <Route element={<AppShell />}>
              <Route index element={<Navigate to="/dashboard" replace />} />
              <Route path="dashboard" element={<Dashboard />} />
              <Route path="cases" element={<Cases />} />
              <Route path="cases/:caseId" element={<CaseView viaConsole={false} />} />
              <Route path="console" element={<Console />} />
              <Route path="console/:caseId" element={<CaseView viaConsole={true} />} />
              <Route path="demo" element={<Demo />} />
              <Route path="*" element={<div className="empty">Not found</div>} />
            </Route>
          </Routes>
        </HashRouter>
      </MerchantProvider>
    </ToastProvider>
  );
}
