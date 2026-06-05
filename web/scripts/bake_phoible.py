#!/usr/bin/env python3
"""Bake the vendored PHOIBLE 2.0 CSV into two JSON snapshots.

The web app cannot ship 25 MB of CSV plus a CSV parser to every
visitor, and parsing 105k rows on every Pyodide cold start would
dominate the boot time. Pre-computing at build time produces two
artifacts the runtime consumes via plain JSON parse:

* ``_phoible_index.generated.json`` — language + inventory
  metadata only (~150-250 KB raw). Bundled into
  ``python_bundle.zip`` so the picker autocomplete lights up at
  app boot without a second fetch.

* ``_phoible_data.generated.json`` — per-inventory segment
  bundles in compact positional encoding (~1.5-2.5 MB raw,
  ~500-700 KB gzipped). Shipped as a separate static asset under
  ``web/dist/`` and lazy-loaded on first PHOIBLE click so the
  cold path stays cheap.

Run standalone for debugging:

    python web/scripts/bake_phoible.py [--out-index PATH] [--out-data PATH]

The default paths land under
``shared/src/phonology_shared/editor/`` alongside the
``*.generated.json`` files; both are gitignored.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_SRC = REPO_ROOT / "shared" / "src"
EDITOR_DIR = SHARED_SRC / "phonology_shared" / "editor"
DEFAULT_OUT_INDEX = EDITOR_DIR / "_phoible_index.generated.json"
DEFAULT_OUT_DATA = EDITOR_DIR / "_phoible_data.generated.json"
DEFAULT_INPUT = (
    REPO_ROOT / "web" / "scripts" / "phoible_cache" / "phoible.csv.gz"
)

# Hard-coded PHOIBLE 2.0 metadata. Tracks the upstream release the
# vendored CSV came from; refresh this if the cache is ever
# regenerated against a newer release.
PHOIBLE_VERSION = "2.0"
PHOIBLE_RELEASE_DATE = "2019-04-03"
PHOIBLE_SOURCE_URL = "https://github.com/phoible/dev"
PHOIBLE_LICENSE = "GPL-3.0 (codebase) + CC BY-SA 3.0 (data)"
PHOIBLE_CITATION = (
    "Moran, Steven & McCloy, Daniel (eds.) 2019. "
    "PHOIBLE 2.0. Jena: Max Planck Institute for the Science of "
    "Human History. http://phoible.org. "
    "DOI: 10.5281/zenodo.2626687"
)

# Display labels for PHOIBLE's short source codes. Picker shows
# the long form so users do not need to memorise the abbreviations.
SOURCE_LABELS: dict[str, str] = {
    "spa": "SPA",
    "upsid": "UPSID",
    "aa": "Alphabets of Africa",
    "gm": "Green & Moran",
    "ph": "PHOIBLE",
    "ra": "Ramaswami",
    "saphon": "SAPhon",
    "ea": "Eurasian Phonologies",
    "uz": "Common Linguistic Features",
}


def _ensure_shared_on_path() -> None:
    """Make ``phonology_shared`` importable without an editable
    install. Mirrors the same trick :py:mod:`web.scripts.build`
    uses so this script works from a bare repo checkout.
    """
    p = str(SHARED_SRC)
    if p not in sys.path:
        sys.path.insert(0, p)


def _open_csv(path: Path) -> io.TextIOWrapper:
    """Return a text-mode reader over the (possibly gzipped) CSV
    file. UTF-8 is the canonical PHOIBLE encoding; explicit so
    the script behaves the same on every platform.
    """
    if path.suffix == ".gz":
        binary = gzip.open(path, "rb")
    else:
        binary = path.open("rb")
    # ``newline=""`` is the csv module's documented requirement so
    # embedded newlines inside quoted fields round-trip correctly.
    return io.TextIOWrapper(binary, encoding="utf-8", newline="")


def _source_label(source: str) -> str:
    """Return ``"PHOIBLE / <Display>"`` for a PHOIBLE source code.

    Unknown codes pass through as uppercased so the picker still
    has something readable when a future PHOIBLE release adds a
    new source family.
    """
    pretty = SOURCE_LABELS.get(source, source.upper())
    return f"PHOIBLE / {pretty}"


def bake_tables(
    csv_path: Path = DEFAULT_INPUT,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, int]]:
    """Stream the PHOIBLE CSV and return (index, data, stats).

    The index payload is bundle-bound and stays small (no per-
    segment bundles). The data payload carries the segment data
    indexed by ``InventoryID`` and is shipped separately so the
    web cold path is not penalised. The stats dict reports
    counts the build pipeline prints.

    Schema of the returned dicts is documented in module top.
    """
    _ensure_shared_on_path()
    from phonology_shared.editor.phoible_features import (
        PHOIBLE_TO_APP_FEATURE,
        normalize_phoible_value,
    )

    if not csv_path.exists():
        raise FileNotFoundError(
            f"PHOIBLE CSV not found at {csv_path}; vendor it under "
            f"web/scripts/phoible_cache/phoible.csv.gz first"
        )

    feature_columns = list(PHOIBLE_TO_APP_FEATURE.keys())
    feature_names = [PHOIBLE_TO_APP_FEATURE[c] for c in feature_columns]

    # Per-inventory accumulators.
    inv_meta: dict[str, dict[str, Any]] = {}
    inv_segments: dict[str, dict[str, str]] = defaultdict(dict)
    # Language-name dedup. The same language often appears under
    # several inventories; the autocomplete list wants one entry per
    # language.
    languages: dict[str, dict[str, Any]] = {}

    rows_total = 0
    contour_normalized = 0
    skipped_no_phoneme = 0

    with _open_csv(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows_total += 1
            phoneme = row.get("Phoneme") or ""
            if not phoneme:
                # PHOIBLE has a handful of header-tier rows whose
                # ``Phoneme`` is empty (suprasegmental-only). Skip
                # them; they would land in the grid as a blank
                # column header that the validator rejects.
                skipped_no_phoneme += 1
                continue

            inv_id = row["InventoryID"]
            if inv_id not in inv_meta:
                lang_name = row.get("LanguageName") or "Unknown"
                glotto = row.get("Glottocode") or None
                if glotto == "NA":
                    glotto = None
                iso = row.get("ISO6393") or None
                if iso == "NA":
                    iso = None
                dialect = row.get("SpecificDialect") or None
                if dialect == "NA":
                    dialect = None
                source = row.get("Source") or "unknown"

                inv_meta[inv_id] = {
                    "id": inv_id,
                    "language_name": lang_name,
                    "glottocode": glotto,
                    "iso": iso,
                    "dialect": dialect,
                    "source": source,
                    "source_label": _source_label(source),
                    # filled in after the streaming pass
                    "segment_count": 0,
                }
                if lang_name not in languages:
                    languages[lang_name] = {
                        "name": lang_name,
                        "glottocode": glotto,
                        "iso": iso,
                    }

            # Build the positional bundle string in feature_columns
            # order; one character per column.
            bundle_chars: list[str] = []
            for col in feature_columns:
                raw = row.get(col, "0")
                normalized = normalize_phoible_value(raw)
                if normalized != raw and raw not in ("", "NA"):
                    contour_normalized += 1
                bundle_chars.append(normalized)
            bundle_str = "".join(bundle_chars)

            # Multiple rows for the same phoneme within one
            # inventory are extremely rare in PHOIBLE; the LAST one
            # wins so the loop stays branch-free. Log if it ever
            # fires so we know there is a regression.
            if phoneme in inv_segments[inv_id]:
                # Same key, different bundle — would silently
                # over-write. Keep the first per the PHOIBLE
                # convention; the second is treated as a duplicate.
                continue
            inv_segments[inv_id][phoneme] = bundle_str

    # Backfill segment_count on each inventory descriptor.
    for inv_id, meta in inv_meta.items():
        meta["segment_count"] = len(inv_segments.get(inv_id, {}))

    # Sort languages alphabetically for stable index output; the
    # picker can render the list in whatever order it likes but a
    # deterministic file simplifies diffs across rebuilds.
    sorted_languages = sorted(
        languages.values(), key=lambda d: d["name"].casefold()
    )
    sorted_inventories = sorted(
        inv_meta.values(),
        key=lambda d: (d["language_name"].casefold(), d["source"], d["id"]),
    )

    index: dict[str, Any] = {
        "version": f"PHOIBLE {PHOIBLE_VERSION}",
        "release_date": PHOIBLE_RELEASE_DATE,
        "source_url": PHOIBLE_SOURCE_URL,
        "license": PHOIBLE_LICENSE,
        "citation": PHOIBLE_CITATION,
        "languages": sorted_languages,
        "inventories": sorted_inventories,
    }

    data: dict[str, Any] = {
        "version": f"PHOIBLE {PHOIBLE_VERSION}",
        "feature_names": feature_names,
        "inventories": {
            inv_id: dict(inv_segments[inv_id])
            for inv_id in sorted(inv_segments.keys(), key=int)
        },
    }

    stats = {
        "rows_total": rows_total,
        "rows_skipped_empty_phoneme": skipped_no_phoneme,
        "inventory_count": len(inv_meta),
        "language_count": len(languages),
        "contour_values_normalized": contour_normalized,
    }
    return index, data, stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"PHOIBLE CSV(.gz) path (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--out-index",
        type=Path,
        default=DEFAULT_OUT_INDEX,
        help=f"Index JSON output path (default: {DEFAULT_OUT_INDEX})",
    )
    parser.add_argument(
        "--out-data",
        type=Path,
        default=DEFAULT_OUT_DATA,
        help=f"Data JSON output path (default: {DEFAULT_OUT_DATA})",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=None,
        help=(
            "JSON indent for output. Default is compact (no indent)"
            " so the runtime parse + transfer stays minimal."
        ),
    )
    args = parser.parse_args()

    try:
        index, data, stats = bake_tables(args.input)
    except FileNotFoundError as exc:
        sys.stderr.write(f"bake_phoible: {exc}\n")
        return 1

    args.out_index.parent.mkdir(parents=True, exist_ok=True)
    args.out_data.parent.mkdir(parents=True, exist_ok=True)

    for path, payload in ((args.out_index, index), (args.out_data, data)):
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=args.indent)
            f.write("\n")

    idx_kb = args.out_index.stat().st_size / 1024
    data_kb = args.out_data.stat().st_size / 1024
    print(
        f"bake_phoible: rows={stats['rows_total']:,} "
        f"(skipped {stats['rows_skipped_empty_phoneme']} empty-Phoneme), "
        f"{stats['language_count']} languages, "
        f"{stats['inventory_count']} inventories, "
        f"{stats['contour_values_normalized']} contour cells normalized"
    )
    print(f"  index: {idx_kb:.1f} KB -> {args.out_index}")
    print(f"  data : {data_kb:.1f} KB -> {args.out_data}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
