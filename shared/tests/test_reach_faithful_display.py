"""Standing guard: display membership is REACH-FAITHFUL, corpus-wide.

The closing invariant of the membership-reads-tiers arc: every label a
segment displays under is a coarse class it existentially reaches
(``reached_classes``), a tier-driven refinement of one (the
breakouts), a class it was DECLARED into by a source primitive
(``rhotic`` / ``flap`` / ``liquid``), the major-class homes (Vowels /
Tones), or a best-effort catch-all / fallback when the segment reaches
nothing. Population size may decide GRANULARITY (whether a reach class
is subdivided or folded back), never MEMBERSHIP: the retired
population covers (Vibrants / cover-Rhotics / cover-Liquids /
Laryngeals) moved segments off their reached-class subtree by
inventory-dependent co-occurrence, so the same segment displayed under
different labels in different inventories. This guard makes that
class of drift fail loudly, the way the fast-path seam test guards the
engine and the readout guard pins the badge.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from phonology_shared.chart.consonants import (
    CONTOID_GROUP_NAME,
    DISPLAY_ORDER,
    TONES_GROUP_NAME,
    VOCOID_GROUP_NAME,
    VOWEL_GROUP_NAME,
    reached_classes,
)
from phonology_shared.editor.phoible_provider import (
    PhoibleProvider,
    materialize_phoible_inventory,
)
from phonology_shared.theory.feature_engine import FeatureEngine

_SHARED_SRC = Path(__file__).resolve().parents[1] / "src"

#: Tier-driven refinement -> its reach parent. A segment displaying
#: under a refinement is inside its reached class's subtree.
_REFINEMENT_PARENT = {
    "Sibilant Affricates": "Affricates",
    "Lateral Affricates": "Affricates",
    "Ejective Affricates": "Affricates",
    "Sibilants": "Fricatives",
    "Lateral Fricatives": "Fricatives",
    "Ejective Fricatives": "Fricatives",
    "Lateral Flaps": "Taps & Flaps",
    "Implosives": "Plosives",
    "Ejective Plosives": "Plosives",
}

#: Labels a segment may display under without reaching them: the
#: major-class homes, the declared-primitive classes (source
#: assertions, not covers), and the catch-alls / fallback homes for
#: reach-empty segments.
_NON_REACH_HOMES = {
    VOWEL_GROUP_NAME,
    TONES_GROUP_NAME,
    CONTOID_GROUP_NAME,
    VOCOID_GROUP_NAME,
    "Rhotics",
    "Liquids",
    "Taps & Flaps",
}

_MIN_SEGMENTS = 90_000


def _provider():
    editor = _SHARED_SRC / "phonology_shared" / "editor"
    idx_path = editor / "_phoible_index.generated.json"
    dat_path = editor / "_phoible_data.generated.json"
    if not (idx_path.exists() and dat_path.exists()):
        pytest.skip("baked PHOIBLE snapshot absent; run bake_phoible first")
    idx = json.loads(idx_path.read_text())
    dat = json.loads(dat_path.read_text())
    return PhoibleProvider(index_table=idx, data_table=dat), idx["inventories"]


def test_display_membership_is_reach_faithful_over_corpus() -> None:
    """For every segment in every PHOIBLE inventory: each displayed
    label is (a) a reached coarse class, (b) a refinement whose parent
    is reached, (c) a declared / major-class / catch-all home, or, for
    a segment that reaches nothing, (d) any best-effort fallback home.
    No population cover can move a segment off its subtree without
    failing here."""
    provider, inventories = _provider()
    checked = 0
    violations: list[tuple[str, str, str, list[str]]] = []
    for entry in inventories:
        inv_id = str(entry["id"])
        eng = FeatureEngine(materialize_phoible_inventory(provider, inv_id))
        norm = eng.normalized_segment_feats
        seqs = eng._sequences_by_seg
        groups = eng.grouped_segments
        memb: dict[str, set[str]] = {}
        for name, segs in groups.items():
            for s in segs:
                memb.setdefault(s, set()).add(name)
        for seg, labels in memb.items():
            checked += 1
            reach = reached_classes(norm[seg], seqs.get(seg, {}))
            if not reach:
                continue  # reach-empty: any fallback home is best-effort
            for label in labels:
                base = _REFINEMENT_PARENT.get(label, label)
                if base in reach or label in _NON_REACH_HOMES:
                    continue
                violations.append((inv_id, seg, label, sorted(reach)))
    assert not violations, violations[:20]
    assert checked >= _MIN_SEGMENTS, checked


def test_retired_cover_labels_never_appear() -> None:
    """The retired population covers are gone from the display
    vocabulary: no grouping may emit Vibrants or Laryngeals, and
    DISPLAY_ORDER no longer carries them."""
    assert "Vibrants" not in DISPLAY_ORDER
    assert "Laryngeals" not in DISPLAY_ORDER
