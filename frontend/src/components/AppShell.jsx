import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useMerchant } from "../context/MerchantContext.jsx";

const NAV = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/cases", label: "Cases" },
  { to: "/console", label: "Agent Console" },
  { to: "/demo", label: "Live Demo" },
];

export function AppShell() {
  const { merchantId, setMerchant } = useMerchant();
  const [navOpen, setNavOpen] = useState(false);
  const location = useLocation();
  const activeSection = location.pathname.startsWith("/console") ? "/console" : location.pathname;

  return (
    <>
      <header className="topbar">
        <div className="brand">
          <span className="mark">&#9702; TORQUE</span>
          <span className="tag">AI Revenue Recovery</span>
        </div>
        <nav className={"nav" + (navOpen ? " open" : "")} id="nav">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={() => (activeSection === item.to ? "active" : "")}
              aria-current={activeSection === item.to ? "page" : undefined}
              onClick={() => setNavOpen(false)}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <label className="merchant">
          merchant
          <input
            type="text"
            spellCheck="false"
            defaultValue={merchantId}
            onBlur={(e) => setMerchant(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") e.target.blur();
            }}
          />
        </label>
        <button
          type="button"
          className="nav-toggle"
          aria-label="Menu"
          aria-expanded={navOpen}
          aria-controls="nav"
          onClick={() => setNavOpen((o) => !o)}
        >
          &#9776;
        </button>
      </header>

      <div className="flow" title="The Torque recovery loop">
        <span>Revenue at Risk</span>
        <i>&rarr;</i>
        <span>AI / Decisioning</span>
        <i>&rarr;</i>
        <span>Recovery Priority</span>
        <i>&rarr;</i>
        <span>Guardrails</span>
        <i>&rarr;</i>
        <span>Action</span>
        <i>&rarr;</i>
        <span>Recovery</span>
        <i>&rarr;</i>
        <span className="flow-end">&#8377; Money Recovered</span>
      </div>

      <main id="view" className="view">
        <Outlet />
      </main>

      <footer className="foot">
        <span>Torque · descriptive recovery reporting · every number derives live from case / action / reconciliation records</span>
      </footer>
    </>
  );
}
