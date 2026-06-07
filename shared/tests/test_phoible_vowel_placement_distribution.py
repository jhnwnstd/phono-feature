"""Diagnostic: per-inventory vowel-placement metric distribution.

Emits one row per PHOIBLE inventory in the 200-inventory sample
(opt-in full corpus via ``PHOIBLE_FULL_CORPUS=1`` env var):

    <lang>/<src>  n_vowels=<N>  default_anchor=<pct>%
                  divergent_split=<count>  refined=<count>
                  conflict=<count>  collisions=<count>
                  worst_cell=<count>

Plus percentile summaries at the end. No hard assertions — this
file is the lens that drives iterative refinement of
:py:mod:`phonology_shared.chart.vowels`. Track each column's p99
across runs; any column whose p99 jumps after a placer edit signals
a regression, any p50 we manage to LOWER signals real progress.

The lens has the same shape as ``test_v5_report_size_distribution``
in the dimensions stress suite, except this one tracks PLACEMENT
quality, not chart-size invariants. Sibling
``test_phoible_vowel_placement_dump.py`` zooms in on per-segment
records for representative inventories.

Skipped when the PHOIBLE bake snapshot is absent.
"""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Callable

import pytest

from phonology_shared.chart.vowels import (
    PlacementFlag,
    compute_placements,
    detect_vowel_profile,
)
from phonology_shared.editor.phoible_provider import (
    materialize_phoible_inventory,
)


def _vowels_of(generated_segments: dict[str, dict[str, str]]) -> list[str]:
    """Same predicate the chart uses: ``Syllabic == '+'``."""
    return [
        seg
        for seg, bundle in generated_segments.items()
        if bundle.get("Syllabic") == "+"
    ]


def _percentiles(values: list[float], *pcts: float) -> dict[float, float]:
    """Tiny percentile helper. Inputs are pre-sorted by the caller."""
    out: dict[float, float] = {}
    if not values:
        for p in pcts:
            out[p] = 0.0
        return out
    n = len(values)
    for p in pcts:
        idx = min(n - 1, int(n * p))
        out[p] = values[idx]
    return out


def _ids_for_run(sample_ids: list[str], full_ids: list[str]) -> list[str]:
    """Pick the inventory list for this run. Default: the sample.
    With ``PHOIBLE_FULL_CORPUS=1``: the full corpus (~3020). The
    full-corpus path is opt-in because it takes ~15x longer."""
    if os.environ.get("PHOIBLE_FULL_CORPUS") == "1":
        return full_ids
    return sample_ids


def _metrics_for_inventory(
    phoible_provider, inv_id: str
) -> dict[str, int | float] | None:
    """Compute the per-inventory metric record. ``None`` when the
    inventory has no vowels (the chart is not rendered)."""
    inv = materialize_phoible_inventory(phoible_provider, inv_id)
    seg_feats = {
        seg: dict(inv.segments[seg])
        for seg, bundle in inv.segments.items()
        if bundle.get("Syllabic") == "+"
    }
    vowels = list(seg_feats)
    if not vowels:
        return None
    profile = detect_vowel_profile(vowels, seg_feats)
    secondary = inv.metadata.get("vowel_secondary")
    secondary_map = secondary if isinstance(secondary, dict) else None
    occupied, placements = compute_placements(
        vowels, profile, seg_feats, vowel_secondary=secondary_map
    )
    n = len(vowels)
    flag_counts: Counter[PlacementFlag] = Counter()
    for placement in placements.values():
        flag_counts.update(placement.flags)
    cells_with_collisions = sum(
        1 for cell_segs in occupied.values() if len(cell_segs) >= 2
    )
    worst_cell = max(
        (len(cell_segs) for cell_segs in occupied.values()), default=0
    )
    return {
        "n_vowels": n,
        "default_anchor_pct": (
            100.0 * flag_counts[PlacementFlag.DEFAULT_ANCHOR] / n
        ),
        "divergent_split": flag_counts[PlacementFlag.SPLIT_SOURCE_DIVERGENCE],
        "refined": flag_counts[PlacementFlag.REFINED],
        "conflict": flag_counts[PlacementFlag.CONFLICT],
        "collisions": cells_with_collisions,
        "worst_cell": worst_cell,
    }


def test_phoible_vowel_placement_distribution(
    phoible_provider,
    phoible_label_for: Callable[[str], str],
    phoible_inventory_ids_sample: list[str],
    phoible_inventory_ids_full: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Diagnostic-only. Iterate the 200-sample (or the full corpus
    when ``PHOIBLE_FULL_CORPUS=1``), compute placement metrics per
    inventory, emit per-inventory rows + percentile summary.

    Pins ONE hard contract: the per-inventory metric record must
    be computable end-to-end (no exceptions from
    ``compute_placements`` for any inventory in the chosen corpus).
    Everything else is observability — the percentile summary is
    the lens that drives Phase 3 refinements.
    """
    ids = _ids_for_run(
        phoible_inventory_ids_sample, phoible_inventory_ids_full
    )
    records: list[tuple[str, dict[str, int | float]]] = []
    for inv_id in ids:
        metrics = _metrics_for_inventory(phoible_provider, inv_id)
        if metrics is None:
            continue
        records.append((phoible_label_for(inv_id), metrics))

    # Per-inventory rows (sorted by default_anchor_pct descending so
    # the worst offenders come first in the captured output).
    records.sort(key=lambda r: r[1]["default_anchor_pct"], reverse=True)
    with capsys.disabled():
        print(
            f"\nPHOIBLE vowel-placement distribution ("
            f"{len(records)} inventories with vowels):"
        )
        # Print the top 20 + bottom 5 so the output stays scannable.
        head = records[:20]
        tail = records[-5:] if len(records) > 25 else []
        for label, m in head:
            print(
                f"  {label:<40s} n_vowels={m['n_vowels']:>2} "
                f"default_anchor={m['default_anchor_pct']:5.1f}%  "
                f"divergent_split={m['divergent_split']:>2}  "
                f"refined={m['refined']:>2}  "
                f"conflict={m['conflict']:>2}  "
                f"collisions={m['collisions']:>2}  "
                f"worst_cell={m['worst_cell']:>2}"
            )
        if tail:
            print("  ...")
            for label, m in tail:
                print(
                    f"  {label:<40s} n_vowels={m['n_vowels']:>2} "
                    f"default_anchor={m['default_anchor_pct']:5.1f}%  "
                    f"divergent_split={m['divergent_split']:>2}  "
                    f"refined={m['refined']:>2}  "
                    f"conflict={m['conflict']:>2}  "
                    f"collisions={m['collisions']:>2}  "
                    f"worst_cell={m['worst_cell']:>2}"
                )

        for key in (
            "default_anchor_pct",
            "divergent_split",
            "refined",
            "conflict",
            "collisions",
            "worst_cell",
        ):
            values = sorted(float(m[key]) for _, m in records)
            pcts = _percentiles(values, 0.5, 0.9, 0.99)
            print(
                f"  {key:<22s} p50={pcts[0.5]:6.2f}  "
                f"p90={pcts[0.9]:6.2f}  "
                f"p99={pcts[0.99]:6.2f}  "
                f"max={values[-1] if values else 0.0:6.2f}"
            )
