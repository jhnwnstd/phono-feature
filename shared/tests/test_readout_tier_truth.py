"""Standing guard: the feature READOUT renders the tier truth the
engine computes; it never re-reads a collapsed single value.

The badge was the last single-phase readout left after the multiset
pass: it printed the collapsed primary value (``mb`` showed ``+`` for
``Sonorant``) while every query read the full value sequence (``mb``
matched ``[-Sonorant]`` too), so a user could watch a segment match
the opposite polarity of the value on screen. The fix classifies by
the value SET the tier-true membership caches carry: a feature whose
sequence reaches both polarities is an ``EXPLICIT_CONFLICT`` and the
row renders ``±``; a single-valued feature renders that value exactly
as before. One source, two renderings: ``find_segments`` and the
badge answer from the same caches.

The corpus guard pins the seam the same way the engine's fast-path
seam test does: for every segment in the baked PHOIBLE corpus, the
singleton classification must equal the value set read independently
off ``Inventory.sequences`` (the ground representation), so the
readout can never again drift from the query answer. Population
floors keep the guard from passing vacuously.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from phonology_shared.data.inventory import Inventory
from phonology_shared.editor.phoible_provider import (
    PhoibleProvider,
    materialize_phoible_inventory,
)
from phonology_shared.theory.feature_engine import (
    FeatureCategory,
    FeatureEngine,
)
from phonology_shared.presentation.view_models import (
    summarize_segment_selection,
)

_SHARED_SRC = Path(__file__).resolve().parents[1] / "src"

# Floors from the current bake (~105k segment occurrences). FLOORS,
# not exact counts, so a PHOIBLE refresh does not churn the guard;
# the divergence list is pinned exactly empty.
_MIN_SEGMENTS_CHECKED = 90_000
_MIN_CONTOUR_CONFLICTS = 500


def _mb_engine() -> FeatureEngine:
    feats = ["Consonantal", "Sonorant", "Continuant", "Nasal", "Syllabic"]
    segs = {
        "mb": {
            "Consonantal": "+",
            "Sonorant": "+",
            "Continuant": "-",
            "Nasal": "+",
            "Syllabic": "-",
        },
        "b": {
            "Consonantal": "+",
            "Sonorant": "-",
            "Continuant": "-",
            "Nasal": "-",
            "Syllabic": "-",
        },
        "a": {
            "Consonantal": "-",
            "Sonorant": "+",
            "Continuant": "+",
            "Nasal": "-",
            "Syllabic": "+",
        },
    }
    inv = Inventory.from_grid(
        name="t",
        features=feats,
        segments=segs,
        metadata={
            "segment_sequences": {
                "mb": {"Sonorant": ["+", "-"], "Nasal": ["+", "-"]}
            }
        },
    )
    return FeatureEngine(inv)


def test_contour_segment_badge_shows_the_set_not_one_phase() -> None:
    """``mb`` alone selected: the ``Sonorant`` and ``Nasal`` rows render
    the contour state (± badge, EXPLICIT_CONFLICT category), never the
    collapsed ``+``; the non-contour ``Continuant`` row still renders
    its single value. This is the readout agreeing with the query: the
    same engine returns ``mb`` for both ``[+Sonorant]`` and
    ``[-Sonorant]``."""
    eng = _mb_engine()
    summary = summarize_segment_selection(eng, ["mb"])
    rows = summary["feature_rows"]
    for feat in ("Sonorant", "Nasal"):
        row = rows[feat]
        assert row["badge"] == "±", (feat, row)
        assert row["category"] == str(FeatureCategory.EXPLICIT_CONFLICT)
        # the row never claims a single shared polarity
        assert row["value"] == ""
        # and the queries the badge must agree with:
        assert "mb" in eng.find_segments({feat: "+"})
        assert "mb" in eng.find_segments({feat: "-"})
    # Non-contour feature: single value, exactly as before.
    cont = rows["Continuant"]
    assert cont["value"] == "-"
    assert cont["badge"] == "−"
    assert cont["category"] == str(FeatureCategory.ALL_MINUS)


def test_single_phase_segment_badges_unchanged() -> None:
    """A plain segment's readout is untouched by the tier-true
    classification: every specified feature shows its single value."""
    eng = _mb_engine()
    rows = summarize_segment_selection(eng, ["b"])["feature_rows"]
    assert rows["Sonorant"]["badge"] == "−"
    assert rows["Sonorant"]["category"] == str(FeatureCategory.ALL_MINUS)
    assert rows["Consonantal"]["badge"] == "+"
    assert rows["Consonantal"]["category"] == str(FeatureCategory.ALL_PLUS)


def _provider() -> tuple[PhoibleProvider, list[dict[str, object]]]:
    editor = _SHARED_SRC / "phonology_shared" / "editor"
    idx_path = editor / "_phoible_index.generated.json"
    dat_path = editor / "_phoible_data.generated.json"
    if not (idx_path.exists() and dat_path.exists()):
        pytest.skip("baked PHOIBLE snapshot absent; run bake_phoible first")
    idx = json.loads(idx_path.read_text())
    dat = json.loads(dat_path.read_text())
    return PhoibleProvider(index_table=idx, data_table=dat), idx["inventories"]


def test_readout_classification_matches_tier_read_over_corpus() -> None:
    """Over the whole corpus, the singleton readout classification for
    every (segment, feature) equals the value set read independently
    off ``Inventory.sequences``: both polarities reached -> conflict
    (the ± badge); one polarity only -> that polarity; nothing explicit
    -> zero. The readout can never drift from the query answer, because
    the queries read the same membership caches this classification
    reads and this guard pins those caches to the ground tiers."""
    provider, inventories = _provider()
    checked = 0
    contour_conflicts = 0
    divergences: list[tuple[str, str, str, str, str]] = []
    for entry in inventories:
        inv_id = str(entry["id"])
        eng = FeatureEngine(materialize_phoible_inventory(provider, inv_id))
        inv = eng.inventory
        for seg in inv.segments:
            checked += 1
            cats = eng.feature_categories([seg])
            seqs = inv.sequences(seg)
            for feat in inv.features:
                values = set(seqs.get(feat, ("0",)))
                explicit = values & {"+", "-"}
                if explicit == {"+", "-"}:
                    expected = FeatureCategory.EXPLICIT_CONFLICT
                elif explicit == {"+"}:
                    expected = FeatureCategory.ALL_PLUS
                elif explicit == {"-"}:
                    expected = FeatureCategory.ALL_MINUS
                else:
                    expected = FeatureCategory.ALL_ZERO
                got = cats[feat]
                if got is not expected:
                    divergences.append(
                        (inv_id, seg, feat, str(expected), str(got))
                    )
                elif expected is FeatureCategory.EXPLICIT_CONFLICT:
                    contour_conflicts += 1
    assert not divergences, divergences[:20]
    # Non-vacuity: the guard must actually exercise the population,
    # including a real body of contour conflicts (the ± rows).
    assert checked >= _MIN_SEGMENTS_CHECKED, checked
    assert contour_conflicts >= _MIN_CONTOUR_CONFLICTS, contour_conflicts
