"""Module 10 §10.14 / §10.15 — the static UI shell is served by the same
process and is wired to the tenant-scoped backend endpoints. (No browser
harness in this stack — the DOM logic is exercised via the API contract it
depends on; here we assert the shell loads and references the right paths.)
"""

from __future__ import annotations

from pathlib import Path

from torque.api.ui import STATIC_DIR


def test_root_redirects_to_ui(make_api_client):
    r = make_api_client().get("/", follow_redirects=False)
    assert r.status_code in (307, 308)
    assert r.headers["location"] == "/ui/"


def test_ui_shell_is_served(make_api_client):
    c = make_api_client()
    r = c.get("/ui/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    assert "TORQUE" in body
    assert "AI Revenue Recovery" in body
    # the product-story flow ribbon is present (§10 intro)
    for step in ("Revenue at Risk", "Guardrails", "Money Recovered"):
        assert step in body
    assert c.get("/ui/torque.css").status_code == 200
    assert c.get("/ui/torque.js").status_code == 200


def test_ui_js_calls_only_tenant_scoped_backend_paths():
    js = (STATIC_DIR / "torque.js").read_text(encoding="utf-8")
    # every data call is scoped to a merchant id or a demo control
    for path in (
        "/reports/${m}/summary",
        "/reports/${m}/top-at-risk",
        "/reports/${m}/human-queue",
        "/reports/${m}/activity",
        "/reports/${m}/cases/${caseId}/events",
        "/agent-console/${m}/cases/${caseId}/",
        "/demo/inject/",
        "/demo/seed",
    ):
        assert path in js, path
    # no cross-tenant / unscoped data path
    assert "/reports/all" not in js
    # no metric is computed in the frontend — the formula stays server-side
    assert "probability *" not in js and "* amount_at_risk" not in js


def test_ui_static_dir_has_the_three_files():
    for name in ("index.html", "torque.css", "torque.js"):
        assert (Path(STATIC_DIR) / name).is_file()
