"""Module 9b — the dashboard's incrementality section is wired to the API and
computes no statistics itself (consistent with the frontend's renderer-only
architecture — see `documentation/demo/ARCHITECTURE.md` for why the source
tree, not the built bundle, is the assertion target after the React
migration).
"""

from __future__ import annotations

from pathlib import Path

from tests.module9b_helpers import cohort_case
from torque.api.ui import STATIC_DIR

FRONTEND_SRC = Path(__file__).resolve().parent.parent / "frontend" / "src"


def _src() -> str:
    parts = []
    for path in sorted(FRONTEND_SRC.rglob("*.js")) + sorted(FRONTEND_SRC.rglob("*.jsx")):
        parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def test_dashboard_fetches_the_incrementality_endpoint():
    src = _src()
    assert "/incrementality" in src
    assert "IncrementalityCard" in src


def test_incrementality_section_renders_only_backend_fields():
    src = _src()
    # reads the response object's fields …
    for ref in (
        "inc.treatment.rate", "inc.control.rate", "inc.lift.point",
        "ci(inc.lift)", "s.lift.point", "ci(s.lift)",
        "s.contaminated_control_counterparties", "s.note",
        "inc.recovery_definition", "o.ci_low", "o.ci_high",
    ):
        assert ref in src, ref
    # … and never re-derives a rate / lift / interval in JS
    assert "treatment.successes / " not in src
    assert "- inc.control.rate" not in src
    assert "wilson" not in src.lower()
    assert "Math.sqrt" not in src


def test_dashboard_distinguishes_descriptive_from_causal():
    src = _src()
    assert "descriptive" in src.lower() and "causal" in src.lower()
    # honest framing — not presented as proven revenue
    assert "Not proof of causation" in src or "not proof" in src.lower()


def test_incrementality_card_is_rendered_from_seeded_data(
    db, make_api_client, make_merchant, make_case
):
    """The seeded dashboard is populated from the /incrementality response
    (served by the same process), and the built bundle actually ships the
    section's label text."""
    m = make_merchant()
    for _ in range(4):
        cohort_case(make_case, m, control=False, recovered=True)
    cohort_case(make_case, m, control=True, recovered=True)
    cohort_case(make_case, m, control=True, recovered=False)
    c = make_api_client()
    body = c.get(f"/reports/{m.merchant_id}/incrementality").json()
    assert body["lift"]["point"] is not None
    # the shell + built JS that render it are both served here
    assert c.get("/ui/").status_code == 200
    assets = STATIC_DIR / "assets"
    bundle = "\n".join(p.read_text(encoding="utf-8") for p in assets.glob("*.js"))
    assert "Incrementality" in bundle
