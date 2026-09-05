"""Module 10 — the UI shell is served by the same process and is wired to
the tenant-scoped backend endpoints.

The frontend was migrated from a hand-written static SPA to a React + Vite
build (see `documentation/demo/ARCHITECTURE.md` for the decision record) —
`STATIC_DIR` now holds a built bundle (`index.html` + a hashed `assets/`
directory) rather than three hand-editable files. The properties this
module locked down under the old architecture still matter under the new
one; each assertion below is re-pointed at the equivalent place:

* server-rendered HTML text checks -> the built JS bundle (a client-rendered
  SPA has no server-rendered body text to scan, so the "will this text ever
  reach the DOM" question is answered by "does the shipped bundle contain
  this string literal");
* API-path / no-client-side-computation / escaping checks -> the frontend
  SOURCE tree (`frontend/src/`), which is the actual human-authored code and
  a strictly more precise place to enforce these invariants than a minified
  bundle (whose local variable names a minifier is free to rename, unlike
  string literals, which it is not).
"""

from __future__ import annotations

import re
from pathlib import Path

from torque.api.ui import STATIC_DIR

FRONTEND_SRC = Path(__file__).resolve().parent.parent / "frontend" / "src"


def _strip_js_comments(js: str) -> str:
    """Good enough for this codebase's comment convention (not a full JS
    parser): strips `/* */` block and `//` line comments so a test can
    assert something is absent from actually *rendered* content, without
    being tripped up by the source's own explanatory comments, which are
    never shown to a user."""
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"(?m)//[^\n]*$", "", js)


def _all_frontend_source() -> str:
    """Every `.js`/`.jsx` file under `frontend/src/`, concatenated. Comments
    stripped, matching the old file's convention for the same kind of
    assertion."""
    parts = []
    for path in sorted(FRONTEND_SRC.rglob("*.js")) + sorted(FRONTEND_SRC.rglob("*.jsx")):
        parts.append(_strip_js_comments(path.read_text(encoding="utf-8")))
    return "\n".join(parts)


def _built_bundle() -> str:
    """The shipped, built JS (and CSS) — what a browser actually receives.
    Used only for "does this string literal ship" checks, since bundling
    can rename local variables but never rewrites string literals."""
    parts = []
    assets = STATIC_DIR / "assets"
    for path in sorted(assets.glob("*.js")) + sorted(assets.glob("*.css")):
        parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def test_root_redirects_to_ui(make_api_client):
    r = make_api_client().get("/", follow_redirects=False)
    assert r.status_code in (307, 308)
    assert r.headers["location"] == "/ui/"


def test_ui_shell_is_served(make_api_client):
    c = make_api_client()
    r = c.get("/ui/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    # a client-rendered SPA's served HTML is an empty mount point — the
    # product-story text ships inside the built JS bundle instead, and
    # renders once that bundle executes in a browser (verified live via
    # browser automation as part of this migration, not by this test).
    bundle = _built_bundle()
    assert "TORQUE" in bundle
    assert "AI Revenue Recovery" in bundle
    for step in ("Revenue at Risk", "Guardrails", "Money Recovered"):
        assert step in bundle


def test_ui_static_dir_has_a_built_spa():
    assert (STATIC_DIR / "index.html").is_file()
    assets = STATIC_DIR / "assets"
    assert assets.is_dir()
    assert list(assets.glob("*.js")), "expected at least one built JS asset"
    assert list(assets.glob("*.css")), "expected at least one built CSS asset"


def test_ui_source_calls_only_tenant_scoped_backend_paths():
    src = _all_frontend_source()
    # every data call is scoped to a merchant id or a demo control — checked
    # against the human-authored source (fixed path segments a bundler
    # cannot rename), not the minified bundle
    for path in (
        "/reports/${",
        "/summary",
        "/top-at-risk",
        "/human-queue",
        "/activity",
        "/cases/${",
        "/events",
        "/over-time",
        "/agent-console/${",
        "/ai/${",
        "/explain",
        "/demo/inject/",
        "/demo/seed",
    ):
        assert path in src, path
    # no cross-tenant / unscoped data path
    assert "/reports/all" not in src
    # no metric is computed in the frontend — the formula stays server-side
    assert "probability *" not in src and "* amount_at_risk" not in src


def test_ui_has_an_explain_case_button_wired_to_the_ai_endpoint():
    src = _all_frontend_source()
    assert 'id="doExplain"' in src
    assert "Explain this case" in src
    assert "/ai/${" in src and "/explain" in src
    # on-demand only: the explain call is reachable only from the button's
    # own click handler, never from a mount-time effect
    assert "onClick={explain}" in src


def test_ui_renders_the_real_case_narrative_schema_not_a_parallel_shape():
    src = _all_frontend_source()
    # every top-level CaseNarrative field (torque.ai.schemas.CaseNarrative)
    # is read directly off the response — no separate frontend narrative shape
    for field in (
        "n.summary",
        "n.current_state",
        "n.root_cause_explanation",
        "n.timeline",
        "n.actions_taken",
        "n.guardrail_explanation",
        "narrative.precedent",  # the case view's local binding for CaseNarrative.precedent
        "n.recommended_human_attention",
        "n.uncertainty",
        "n.evidence_gaps",
        "n.provider_id",
        "n.prompt_version",
    ):
        assert field in src, field
    # narrative text is never raw-interpolated as executable HTML: React
    # auto-escapes every JSX text expression by default, and this codebase
    # never opts out of that guarantee (see the dangerouslySetInnerHTML
    # check below) — a stronger, structurally-enforced version of the old
    # "esc() called before innerHTML" convention.


def test_ui_citation_click_navigates_to_the_existing_event_timeline():
    src = _all_frontend_source()
    # the audit trail's own <li> carries the anchor citations navigate to —
    # no second/parallel event timeline is introduced for this
    assert "data-event-seq={e.event_seq_id}" in src
    assert "focusCitation" in src
    # a citation id is validated with a strict pattern before it becomes
    # part of a CSS selector — never used as a raw/unchecked selector
    assert "/^case_event:(\\d+)$/" in src
    assert 'li[data-event-seq="${m[1]}"]' in src


def test_ui_never_bypasses_reacts_default_escaping():
    """React escapes every JSX text expression by default; the one way to
    defeat that is `dangerouslySetInnerHTML`. Asserting its absence is a
    stronger, structurally-enforced replacement for the old hand-written
    `esc()`-before-`innerHTML` convention (which required remembering to
    call `esc()` at every interpolation site)."""
    src = _all_frontend_source()
    assert "dangerouslySetInnerHTML" not in src


def test_ui_ai_error_states_never_leak_raw_exception_text():
    src = _all_frontend_source()
    # the AiAssessment error path always renders one of a few fixed, generic
    # messages selected by HTTP status — never `e.message` (the backend's
    # raw HTTPException detail) interpolated into the AI panel
    assert '<div className="ai-error">{state.msg}</div>' in src
    assert "e.message" not in src.split("const explain = async")[1].split("\n  };")[0]


def test_ui_explain_button_disabled_during_request_and_reenabled_after():
    """Repeated clicks on "Explain this case" must not fire overlapping
    requests while one is already in flight, and must not permanently
    disable the button after a failed request either."""
    src = _all_frontend_source()
    body = src.split("const explain = async")[1].split("\n  };")[0]
    assert 'setState({ status: "loading" })' in body
    # both the success path and the error path resolve out of "loading" —
    # so the button (bound to status === "loading") always re-enables
    assert 'setState({ status: "ok"' in body
    assert 'setState({ status: "error"' in body


def test_ui_ai_panel_starts_empty_so_no_stale_narrative_survives_a_case_switch():
    """`AiAssessment` is mounted with `key={caseId}` — React unmounts and
    remounts it (resetting its internal state to idle) on every case
    switch, so a previously-rendered narrative can never bleed into a
    newly-selected case's panel. The React-appropriate replacement for the
    old "full innerHTML replace on every render" guarantee."""
    src = _all_frontend_source()
    assert "key={caseId}" in src
    assert '<AiAssessment key={caseId}' in src


def test_ui_over_time_graph_renders_only_real_backend_values():
    src = _all_frontend_source()
    # the zero-padding fix reads only the real `recovered_amount` the
    # backend returned (defaulted to the string "0", not a random/fabricated
    # number) for the synthetic filler periods it adds so a sparse series
    # still reads as a trend rather than one full-width bar
    assert 'recovered_amount: "0"' in src
    assert "Math.random" not in src
    # bar/point height is still a pure function of `recovered_amount` — no
    # local recomputation of a rate/score the backend already owns
    assert "Number(s.recovered_amount)" in src or "Number(p.recovered_amount)" in src


def test_ui_has_no_documentation_artifacts_outside_comments():
    """Internal documentation/implementation metadata (section numbers,
    module/phase names, blueprint terminology) must never appear in
    anything the frontend actually renders. It is fine, and expected, for
    the source's own explanatory comments to mention them — those are never
    shown to a user, so they are excluded here rather than asserted away."""
    src = _all_frontend_source()
    for artifact in ("§", "Blueprint", "AI Phase", "Module 8", "Module 9", "Module 10"):
        assert artifact not in src, artifact

    index_html = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
    html = index_html.read_text(encoding="utf-8")
    for artifact in ("§", "Blueprint", "Module 8", "Module 9", "Module 10"):
        assert artifact not in html, artifact
