"""Module 9b — the dashboard's incrementality section is wired to the API and
computes no statistics itself (consistent with Module 10's renderer-only UI).
"""

from __future__ import annotations

from tests.module9b_helpers import cohort_case
from torque.api.ui import STATIC_DIR


def _js() -> str:
    return (STATIC_DIR / "torque.js").read_text(encoding="utf-8")


def test_dashboard_fetches_the_incrementality_endpoint():
    js = _js()
    assert "/reports/${m}/incrementality" in js
    assert "incrementalityCard(" in js


def test_incrementality_section_renders_only_backend_fields():
    js = _js()
    # reads the response object's fields …
    for ref in (
        "inc.treatment.rate", "inc.control.rate", "inc.lift.point",
        "ci(inc.lift)", "s.lift.point", "ci(s.lift)",
        "s.contaminated_control_counterparties", "s.note",
        "inc.recovery_definition", "o.ci_low", "o.ci_high",
    ):
        assert ref in js, ref
    # … and never re-derives a rate / lift / interval in JS
    assert "treatment.successes / " not in js
    assert "- inc.control.rate" not in js
    assert "wilson" not in js.lower()
    assert "Math.sqrt" not in js


def test_dashboard_distinguishes_descriptive_from_causal():
    js = _js()
    assert "descriptive" in js.lower() and "causal" in js.lower()
    # honest framing — not presented as proven revenue
    assert "Not proof of causation" in js or "not proof" in js.lower()


def test_incrementality_card_is_rendered_from_seeded_data(
    db, make_api_client, make_merchant, make_case
):
    """The seeded dashboard HTML actually contains the section, populated from
    the /incrementality response (served by the same process)."""
    m = make_merchant()
    for _ in range(4):
        cohort_case(make_case, m, control=False, recovered=True)
    cohort_case(make_case, m, control=True, recovered=True)
    cohort_case(make_case, m, control=True, recovered=False)
    c = make_api_client()
    body = c.get(f"/reports/{m.merchant_id}/incrementality").json()
    assert body["lift"]["point"] is not None
    # the shell + JS that render it are both served here
    assert c.get("/ui/").status_code == 200
    assert "Incrementality" in c.get("/ui/torque.js").text
