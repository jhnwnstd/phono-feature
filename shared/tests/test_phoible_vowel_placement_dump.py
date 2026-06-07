"""Diagnostic: per-segment vowel-placement record on representative
PHOIBLE inventories.

Picks one inventory per (n_vowels bucket, has_diphthongs flag)
combination from the 200-inventory sample, then prints the full
placement record for every vowel:

    <lang>/<src>: N vowels
      i  → (row=Close,       col=front,   conf=HIGH,   flags=DIRECT)
      ɨ  → (row=Close,       col=central, conf=HIGH,   flags=DIRECT)
      ã̃i → (row=Open-mid,    col=central, conf=LOW,
            flags=UNDERSPECIFIED|DEFAULT_ANCHOR)
      ...

This is the lens we read by hand to spot "is this placement
actually right?" — issues the aggregate percentile lens
(``test_phoible_vowel_placement_distribution``) can't show. No
hard assertions beyond contract guards.

Skipped when the PHOIBLE bake snapshot is absent.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from phonology_shared.chart.vowels import (
    ROW_LABELS,
    compute_placements,
    detect_vowel_profile,
)
from phonology_shared.editor.phoible_provider import (
    materialize_phoible_inventory,
)

_COL_LABELS: tuple[str, ...] = (
    "front-unr",
    "front-rnd",
    "central-unr",
    "central-rnd",
    "back-unr",
    "back-rnd",
    "front-neu",
    "central-neu",
    "back-neu",
)


def _vowel_size_bucket(n: int) -> str:
    """Coarse bucket the dump uses to pick one inventory per
    cardinality + diphthong combo. Boundaries chosen so each
    bucket actually has a member in the 200-sample."""
    if n <= 4:
        return "tiny"
    if n <= 7:
        return "small"
    if n <= 12:
        return "medium"
    if n <= 20:
        return "large"
    return "huge"


def _has_diphthongs(inv) -> bool:
    vs = inv.metadata.get("vowel_secondary") or {}
    return bool(vs)


def _format_placement(seg: str, placement) -> str:
    row_label = (
        ROW_LABELS[placement.row]
        if 0 <= placement.row < len(ROW_LABELS)
        else f"row?({placement.row})"
    )
    col_label = (
        _COL_LABELS[placement.col]
        if 0 <= placement.col < len(_COL_LABELS)
        else f"col?({placement.col})"
    )
    flags = "|".join(sorted(str(f) for f in placement.flags)) or "(none)"
    line = (
        f"    {seg:<6s} → (row={row_label:<10s} "
        f"col={col_label:<12s} "
        f"conf={placement.confidence.name:<6s} "
        f"flags={flags})"
    )
    if placement.secondary is not None:
        sec = placement.secondary
        sec_row = (
            ROW_LABELS[sec.row]
            if 0 <= sec.row < len(ROW_LABELS)
            else f"row?({sec.row})"
        )
        sec_col = (
            _COL_LABELS[sec.col]
            if 0 <= sec.col < len(_COL_LABELS)
            else f"col?({sec.col})"
        )
        line += f"  ↪ secondary=({sec_row}, {sec_col})"
    return line


def test_phoible_vowel_placement_dump(
    phoible_provider,
    phoible_label_for: Callable[[str], str],
    phoible_inventory_ids_sample: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Pick one inventory per bucket and dump per-segment
    placements + feature evidence. Diagnostic only."""
    # Bucket the sample once.
    bucketed: dict[tuple[str, bool], tuple[str, object, list[str]]] = {}
    for inv_id in phoible_inventory_ids_sample:
        inv = materialize_phoible_inventory(phoible_provider, inv_id)
        vowels = [
            seg
            for seg, bundle in inv.segments.items()
            if bundle.get("Syllabic") == "+"
        ]
        if not vowels:
            continue
        key = (_vowel_size_bucket(len(vowels)), _has_diphthongs(inv))
        # First inventory per bucket wins (the sample is already
        # deterministically shuffled by seed-42).
        if key not in bucketed:
            bucketed[key] = (inv_id, inv, vowels)

    with capsys.disabled():
        print(
            f"\nPHOIBLE vowel-placement per-segment dump "
            f"({len(bucketed)} buckets):\n"
        )
        # Stable iteration: bucket name + diphthongs flag.
        for (bucket, has_di), (inv_id, inv, vowels) in sorted(
            bucketed.items()
        ):
            label = phoible_label_for(inv_id)
            seg_feats = {seg: dict(inv.segments[seg]) for seg in vowels}
            profile = detect_vowel_profile(vowels, seg_feats)
            secondary = inv.metadata.get("vowel_secondary")
            secondary_map = secondary if isinstance(secondary, dict) else None
            _, placements = compute_placements(
                vowels,
                profile,
                seg_feats,
                vowel_secondary=secondary_map,
            )
            tag = "diphthongs" if has_di else "monophthongs"
            print(f"[{bucket:<6s} {tag:<12s}] {label}  ({len(vowels)} vowels)")
            for seg in vowels:
                p = placements.get(seg)
                if p is None:
                    print(f"    {seg}  ← MISSING placement")
                    continue
                print(_format_placement(seg, p))
                # Inline the feature trio the divergence detector
                # reads. PHOIBLE bundles arrive PascalCase
                # (``Tense``, ``ATR``, ...); the placer lowercases
                # before reading, so the dump does too — otherwise
                # the printed feats wouldn't match the placement
                # logic and the diagnostic would mislead.
                f_lower = {k.lower(): v for k, v in seg_feats[seg].items()}
                trio = (
                    f"tense={f_lower.get('tense', '-')}  "
                    f"atr={f_lower.get('atr', '-')}  "
                    f"rtr={f_lower.get('rtr', '-')}  "
                    f"high={f_lower.get('high', '-')}  "
                    f"low={f_lower.get('low', '-')}  "
                    f"front={f_lower.get('front', '-')}  "
                    f"back={f_lower.get('back', '-')}"
                )
                print(f"          feats: {trio}")
            print()
