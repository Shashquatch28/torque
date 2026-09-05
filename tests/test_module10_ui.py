"""Module 10 §10.14 / §10.15 — the static UI shell is served by the same
process and is wired to the tenant-scoped backend endpoints. (No browser
harness in this stack — the DOM logic is exercised via the API contract it
depends on; here we assert the shell loads and references the right paths.)

Phase 6 extends this file (rather than starting a separate UI test module)
with the same static-source-inspection style: the Agent Console's AI surface
references the right endpoint, the citation-navigation wiring exists, the
narrative is rendered from the real `CaseNarrative` schema (not a parallel
shape), the dashboard graph still only ever renders backend-supplied values,
and no internal documentation/blueprint label leaked into anything the JS
actually renders (as opposed to comments, which are never shown to a user).
"""

from __future__ import annotations

import re
from pathlib import Path

from torque.api.ui import STATIC_DIR


def _strip_js_comments(js: str) -> str:
    """Good enough for this hand-written, comment-convention-consistent
    file (not a full JS parser): strips `/* */` block and `//` line
    comments so a test can assert something is absent from actually
    *rendered* content specifically, without being tripped up by the
    file's own extensive `// --- section (§10.x) ---` comments, which are
    never shown to a user."""
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"(?m)//[^\n]*$", "", js)


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
        "/reports/${m}/over-time",
        "/agent-console/${m}/cases/${caseId}/",
        "/ai/${m}/cases/${caseId}/explain",
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


# --- Phase 6: Agent Console AI surface ------------------------------------


def test_ui_has_an_explain_case_button_wired_to_the_ai_endpoint():
    js = (STATIC_DIR / "torque.js").read_text(encoding="utf-8")
    assert 'id="doExplain"' in js
    assert "Explain this case" in js
    assert "/ai/${m}/cases/${caseId}/explain" in js
    # on-demand only (§26) — never fetched as part of the case-pane's own
    # initial Promise.all load, only from the button's own click handler
    assert 'onclick = () => explainCase(m, caseId, pane)' in js


def test_ui_renders_the_real_case_narrative_schema_not_a_parallel_shape():
    js = (STATIC_DIR / "torque.js").read_text(encoding="utf-8")
    # every top-level CaseNarrative field (torque.ai.schemas.CaseNarrative)
    # is read directly off the response — no separate frontend narrative shape
    for field in (
        "n.summary",
        "n.current_state",
        "n.root_cause_explanation",
        "n.timeline",
        "n.actions_taken",
        "n.guardrail_explanation",
        "n.precedent",
        "n.recommended_human_attention",
        "n.uncertainty",
        "n.evidence_gaps",
        "n.provider_id",
        "n.prompt_version",
    ):
        assert field in js, field
    # narrative text is escaped, never raw-interpolated as executable HTML
    assert "esc(n.summary)" in js
    assert "esc(nc.claim)" in js


def test_ui_citation_click_navigates_to_the_existing_event_timeline():
    js = (STATIC_DIR / "torque.js").read_text(encoding="utf-8")
    # the audit trail's own <li> carries the anchor citations navigate to —
    # no second/parallel event timeline is introduced for this
    assert 'data-event-seq="${e.event_seq_id}"' in js
    assert "closest(\"[data-cite]\")" in js
    assert "focusCitation" in js
    # a citation id is validated with a strict pattern before it becomes
    # part of a CSS selector — never used as a raw/unchecked selector
    assert "/^case_event:(\\d+)$/" in js
    assert 'li[data-event-seq="${m[1]}"]' in js


def test_ui_ai_error_states_never_leak_raw_exception_text():
    js = (STATIC_DIR / "torque.js").read_text(encoding="utf-8")
    # explainCase's catch block always renders one of a few fixed, generic
    # messages selected by HTTP status — never `e.message` (which is the
    # backend's raw HTTPException detail) interpolated into the AI panel
    assert "out.innerHTML = `<div class=\"ai-error\">${esc(msg)}</div>`" in js
    assert "${esc(e.message)}" not in js.split("async function explainCase")[1].split(
        "\n}\n"
    )[0]


def test_ui_precedent_table_escapes_root_cause_code():
    """Phase 8 hardening: `root_cause_code` is a free `String(64)` column
    with no enum/CHECK (D-014) — every other AI-rendered field already goes
    through `esc()` before `innerHTML`; `renderPrecedent`'s
    `titleize(pc.root_cause_code)` did not, and was fixed to
    `esc(titleize(pc.root_cause_code))`. Guards against this regressing."""
    js = (STATIC_DIR / "torque.js").read_text(encoding="utf-8")
    assert "esc(titleize(pc.root_cause_code))" in js
    assert "${titleize(pc.root_cause_code)}" not in js


def test_ui_explain_button_disabled_during_request_and_reenabled_after():
    """Phase 8 hardening: repeated clicks on "Explain this case" must not
    fire overlapping requests while one is already in flight, and must not
    permanently disable the button after a failed request either."""
    js = (STATIC_DIR / "torque.js").read_text(encoding="utf-8")
    body = js.split("async function explainCase")[1].split("\nasync function")[0]
    disable_idx = body.index("btn.disabled = true;")
    try_idx = body.index("try {")
    reenable_idx = body.rindex("btn.disabled = false;")
    catch_idx = body.index("} catch")
    # disabled BEFORE the request starts, re-enabled AFTER the try/catch
    # block ends (unconditionally -- on both the success and error paths)
    assert disable_idx < try_idx < reenable_idx
    assert catch_idx < reenable_idx


def test_ui_ai_panel_starts_empty_so_no_stale_narrative_survives_a_case_switch():
    """Phase 8 hardening: `renderConsolePane` fully replaces the case pane's
    `innerHTML` (including a fresh, empty `#aiPanel`) every time a case is
    selected -- a previously-rendered narrative can never bleed into a
    newly-selected case's pane."""
    js = (STATIC_DIR / "torque.js").read_text(encoding="utf-8")
    assert '<div id="aiPanel"></div>' in js


def test_ui_over_time_graph_renders_only_real_backend_values():
    js = (STATIC_DIR / "torque.js").read_text(encoding="utf-8")
    # the zero-padding fix reads only the real `recovered_amount` the
    # backend returned (defaulted to the string "0", not a random/fabricated
    # number) for the synthetic filler days it adds so a sparse series still
    # reads as a trend rather than one full-width bar
    assert 'recovered_amount: "0"' in js
    assert "Math.random" not in js
    # bar height is still a pure function of `s.recovered_amount` — no local
    # recomputation of a rate/score the backend already owns
    assert "Number(s.recovered_amount)" in js


def test_ui_has_no_documentation_artifacts_outside_comments():
    """§15 — internal documentation/implementation metadata (section
    numbers, module/phase names, blueprint terminology) must never appear
    in anything the JS actually renders. It is fine, and expected, for the
    file's own `// --- section (§10.x) ---` organizational comments to
    mention them — those are never shown to a user, so they are excluded
    here rather than asserted away."""
    js = (STATIC_DIR / "torque.js").read_text(encoding="utf-8")
    code_only = _strip_js_comments(js)
    for artifact in ("§", "Blueprint", "AI Phase", "Module 8", "Module 9", "Module 10"):
        assert artifact not in code_only, artifact

    css = (STATIC_DIR / "torque.css").read_text(encoding="utf-8")
    css_code_only = _strip_js_comments(css)  # CSS uses the same /* */ syntax
    for artifact in ("§", "Blueprint", "AI Phase", "Module 8", "Module 9", "Module 10"):
        assert artifact not in css_code_only, artifact

    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    for artifact in ("§", "Blueprint", "Module 8", "Module 9", "Module 10"):
        assert artifact not in html, artifact
