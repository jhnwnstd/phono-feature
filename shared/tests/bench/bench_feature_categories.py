"""Microbenchmark for :py:meth:`FeatureEngine.feature_categories`.

Run manually with::

    python shared/tests/bench/bench_feature_categories.py

Excluded from the default ``pytest`` run because the script does I/O
plus timing assertions that are flaky on a busy CI host. The numbers
exist to gate the cache-or-not decision in the Phase 5 plan: if the
per-call cost on Hayes (28 features) at the canonical selection
sizes is below 0.5 ms, no cache is worth adding; the algorithmic
change would be premature.

The benchmark uses :py:func:`timeit.repeat` with a small number of
loops because the function returns in well under a millisecond per
call on a 2026-era laptop; we want a tight stddev, not a huge total
runtime.
"""

from __future__ import annotations

import json
import timeit
from pathlib import Path

from phonology_shared.data.inventory import Inventory
from phonology_shared.theory.feature_engine import FeatureEngine

INVENTORY_PATH = (
    Path(__file__).resolve().parents[3]
    / "desktop"
    / "inventories"
    / "hayes_features.json"
)
SAMPLE_COUNTS: tuple[int, ...] = (1, 5, 15, 0)  # 0 means "all segments"


def _load_engine() -> FeatureEngine:
    raw = json.loads(INVENTORY_PATH.read_text(encoding="utf-8-sig"))
    return FeatureEngine(Inventory.parse(raw, source=str(INVENTORY_PATH)))


def _bench(engine: FeatureEngine, selection: list[str], label: str) -> None:
    """Time ``feature_categories(selection)`` and print the median
    per-call cost in microseconds plus the worst-case from the
    five repeats. Loops chosen so each repeat takes ~10 ms total.
    """
    loops = 2000
    times = timeit.repeat(
        stmt=lambda: engine.feature_categories(selection),
        number=loops,
        repeat=5,
    )
    per_call_us = [t / loops * 1_000_000 for t in times]
    median = sorted(per_call_us)[len(per_call_us) // 2]
    worst = max(per_call_us)
    print(
        f"  {label:>14s}: median {median:7.2f} us/call, "
        f"worst {worst:7.2f} us/call ({len(selection)} segs)"
    )


def main() -> None:
    engine = _load_engine()
    n_features = len(engine.features)
    all_segs = list(engine.segments)
    n_segments = len(all_segs)
    print(
        f"feature_categories microbench on Hayes "
        f"({n_segments} segs x {n_features} feats):"
    )
    for k in SAMPLE_COUNTS:
        if k == 0:
            label = "all"
            sample = all_segs
        else:
            label = f"size={k}"
            sample = all_segs[:k]
        _bench(engine, sample, label)
    print(
        "\nThreshold for caching: median >= 500 us/call at any size."
    )


if __name__ == "__main__":
    main()
