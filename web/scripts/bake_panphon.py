#!/usr/bin/env python3
"""Bake PanPhon's IPA -> features table into a JSON snapshot.

The web app cannot afford to ship pandas + numpy + panphon to every
visitor (~120 MB uncompressed). PanPhon's behaviour for our single-
segment lookup case is data-driven: it walks ``ipa_all.csv`` into a
DataFrame, then resolves each user-typed symbol against that table.
We can substitute a pure-Python dict lookup with byte-identical
output by pre-computing the table at build time, baking it as JSON,
and shipping the JSON into the web bundle.

Output: ``shared/src/phonology_shared/editor/_panphon_table.generated.json``

That path is gitignored; the bake step is invoked by
:py:mod:`web.scripts.build` before zipping ``phonology_shared`` into
the Pyodide bundle, so a clean checkout always produces a fresh
snapshot from the installed ``panphon``.

Run standalone for debugging:
    python web/scripts/bake_panphon.py [--out path]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_SRC = REPO_ROOT / "shared" / "src"
DEFAULT_OUT = (
    SHARED_SRC
    / "phonology_shared"
    / "editor"
    / "_panphon_table.generated.json"
)


def _ensure_shared_on_path() -> None:
    """Make ``phonology_shared`` importable without an editable install.

    Mirrors the trick :py:mod:`web.scripts.build` uses to keep this
    script invokable from a bare repo checkout.
    """
    p = str(SHARED_SRC)
    if p not in sys.path:
        sys.path.insert(0, p)


def bake_table() -> dict[str, object]:
    """Walk PanPhon's FeatureTable into a JSON-serializable dict.

    Schema (compact encoding):
        {
          "provider_name": "PanPhon",
          "provider_version": "<panphon.__version__>",
          "feature_names": ["Syllabic", "Sonorant", ...],
          "segments": {
            "<ipa>": "+-+--+...",
            ...
          }
        }

    Each segment maps to a single string whose i-th character is the
    feature value (``"+"`` / ``"-"`` / ``"0"``) for
    ``feature_names[i]``. A naive ``{feature: value}`` dict per
    segment blew the JSON to ~2.5 MB (6.4k segments times 24
    features times keys/quotes/braces); the positional encoding
    drops it to ~150 KB at the cost of one ``zip`` call when the
    runtime provider materialises a bundle. Wire-compatible: the
    runtime decoder rebuilds the dict with
    ``dict(zip(feature_names, segment_string))``.

    ``feature_names`` is the subset of PanPhon's column names that
    has an app-side mapping, preserved in PanPhon's column order so
    this matches what the desktop's live provider exposes.
    """
    _ensure_shared_on_path()
    import importlib.metadata

    import panphon

    from phonology_shared.editor.panphon_features import (
        PANPHON_TO_APP_FEATURE,
        panphon_value_to_app,
    )

    ft = panphon.FeatureTable()
    panphon_names = list(ft.names)
    feature_names = tuple(
        PANPHON_TO_APP_FEATURE[name]
        for name in panphon_names
        if name in PANPHON_TO_APP_FEATURE
    )

    # Indices into the panphon name vector that correspond to a
    # mapped app feature, in feature_names order. Computed once so
    # the per-segment loop is a tight slice + join.
    kept_indices = [
        i
        for i, pname in enumerate(panphon_names)
        if pname in PANPHON_TO_APP_FEATURE
    ]
    expected_n = len(panphon_names)

    segments: dict[str, str] = {}
    for ipa, seg_obj in ft.segments:
        # PanPhon's ``Segment.strings()`` yields ``"+" / "-" / "0"``
        # in the same column order as ``ft.names``. ``numeric()`` is
        # the forward-compat fallback for a future PanPhon where the
        # default representation changes.
        if hasattr(seg_obj, "strings"):
            values = list(seg_obj.strings())
        elif hasattr(seg_obj, "numeric"):
            values = list(seg_obj.numeric())
        else:
            raise TypeError(
                f"PanPhon Segment for {ipa!r} has neither strings() "
                f"nor numeric(); bake aborted"
            )
        if len(values) != expected_n:
            raise ValueError(
                f"PanPhon returned {len(values)} values for "
                f"{expected_n} names on segment {ipa!r}"
            )
        # Coerce each kept value into the three-char vocabulary and join
        # into the positional string the runtime decodes against
        # ``feature_names``.
        segments[ipa] = "".join(
            panphon_value_to_app(values[idx]) for idx in kept_indices
        )

    try:
        version = importlib.metadata.version("panphon")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"

    return {
        "provider_name": "PanPhon",
        "provider_version": version,
        "feature_names": list(feature_names),
        "segments": segments,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output JSON path (default: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=None,
        help=(
            "Indent for the JSON output. Default writes compact form "
            "(no indent, no spaces) so the runtime fetch is small."
        ),
    )
    args = parser.parse_args()

    try:
        table = bake_table()
    except ImportError as exc:
        sys.stderr.write(
            f"bake_panphon: panphon is not installed in this venv "
            f"({exc}); install it via "
            f"`pip install -e desktop[panphon]` or "
            f"`uv sync --all-packages --all-extras`.\n"
        )
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        json.dump(table, f, ensure_ascii=False, indent=args.indent)
        f.write("\n")
    n_seg = len(table["segments"])
    n_feat = len(table["feature_names"])
    size_kb = args.out.stat().st_size / 1024
    print(
        f"bake_panphon: wrote {n_seg} segments x {n_feat} features "
        f"({size_kb:.1f} KB) to {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
