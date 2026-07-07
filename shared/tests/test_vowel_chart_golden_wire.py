"""Golden-snapshot tripwire for the vowel-chart wire payload.

The vowel-chart section of the wire payload (silhouette corners,
column projections, cell chart_x / chart_y, row anchors) is the exact
data both renderers paint. Any refactor of the geometry pipeline that
changes ONE number here is a semantic drift the eye may not catch on
a single-inventory screenshot but that surfaces later as an outline
that no longer wraps its buttons or a guide that misses a cell
midpoint. The two goldens cover both branches the pipeline can take:
Hayes exercises the classic trapezoid with a maximal Open row;
Spanish exercises the converged-bottom shape (single low central
/a/ triggers ``open_apex_backness = "central"``).

To regenerate after an intentional semantic change:

    python -c "
    import json
    from phonology_shared.presentation.view_models import build_inventory_summary
    from phonology_shared.data.inventory import Inventory
    from phonology_shared.theory.feature_engine import FeatureEngine
    for stem in ('hayes_features', 'spanish_features'):
        p = f'desktop/inventories/{stem}.json'
        raw = json.loads(open(p, encoding='utf-8-sig').read())
        inv = Inventory.parse(raw, source=p)
        eng = FeatureEngine(inv)
        summary = build_inventory_summary(eng, stem)
        with open(f'shared/tests/goldens/vowel_chart_{stem}.json', 'w') as f:
            json.dump(summary['vowel_chart'], f, indent=2,
                     sort_keys=True, ensure_ascii=False)
    "

Regenerating without a corresponding, deliberate design decision
defeats the tripwire. Read the diff before overwriting.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from phonology_shared.data.inventory import Inventory
from phonology_shared.presentation.view_models import build_inventory_summary
from phonology_shared.theory.feature_engine import FeatureEngine

_GOLDEN_DIR = Path(__file__).parent / "goldens"
_INVENTORY_DIR = (
    Path(__file__).resolve().parents[2] / "desktop" / "inventories"
)


def _load_golden(stem: str) -> dict:
    return json.loads(
        (_GOLDEN_DIR / f"vowel_chart_{stem}.json").read_text(
            encoding="utf-8"
        )
    )


def _build_wire(stem: str) -> dict:
    path = _INVENTORY_DIR / f"{stem}.json"
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    inv = Inventory.parse(raw, source=str(path))
    eng = FeatureEngine(inv)
    summary = build_inventory_summary(eng, stem)
    return summary["vowel_chart"]


@pytest.mark.parametrize("stem", ["hayes_features", "spanish_features"])
def test_vowel_chart_wire_matches_golden(stem: str) -> None:
    """The vowel-chart wire payload for a bundled inventory has not
    drifted from its pinned snapshot.

    Compared as sorted-key JSON so field-order changes in the view-
    model emitter are ignored; floats are compared VALUE-EQUAL (not
    ``pytest.approx``) so any drift, however small, surfaces here.
    """
    golden = _load_golden(stem)
    live = _build_wire(stem)
    live_json = json.dumps(live, sort_keys=True, ensure_ascii=False, indent=2)
    golden_json = json.dumps(
        golden, sort_keys=True, ensure_ascii=False, indent=2
    )
    if live_json != golden_json:
        # Emit the FIRST diff-line so the failure message points at a
        # concrete drift; a full unified diff would blow up the CI log.
        for i, (a, b) in enumerate(
            zip(live_json.splitlines(), golden_json.splitlines())
        ):
            if a != b:
                pytest.fail(
                    f"{stem} vowel-chart wire drifted at line {i + 1}: "
                    f"\n  live:   {a}\n  golden: {b}\n"
                    "If this is an intentional change, regenerate the "
                    "golden via the recipe in the module docstring."
                )
        pytest.fail(
            f"{stem} vowel-chart wire drifted (length changed: "
            f"live={len(live_json)} vs golden={len(golden_json)})"
        )
