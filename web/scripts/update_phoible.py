#!/usr/bin/env python3
"""Refresh the vendored PHOIBLE source files from upstream, pinned.

One command re-fetches the two upstream files the bake reads
(``data/phoible.csv`` and ``mappings/InventoryID-Bibtex.csv`` from
``phoible/dev``), gzips them deterministically into this cache, and
writes ``PROVENANCE.json`` recording the exact ref, resolved commit
sha, fetch time, and per-file checksums. That makes "stay current with
upstream" a single reproducible step instead of a hand-run
``curl | gzip`` pipe.

    # published PHOIBLE 2.0 release
    python web/scripts/update_phoible.py

    # latest upstream, an exact past state, or another release tag
    python web/scripts/update_phoible.py --ref <branch-or-commit-sha-or-tag>

After refreshing, re-bake and verify:

    python web/scripts/bake_phoible.py
    cd shared && pytest

The gzip output is written with a fixed mtime so an unchanged upstream
file produces a byte-identical ``.gz`` (no spurious diff / build-id
churn). ``bake_phoible.py`` reads the release metadata back out of
``PROVENANCE.json`` so a refresh updates the baked version stamp
without a second manual edit.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

CACHE_DIR = Path(__file__).resolve().parent / "phoible_cache"
PROVENANCE_PATH = CACHE_DIR / "PROVENANCE.json"

UPSTREAM_REPO = "phoible/dev"
UPSTREAM_URL = f"https://github.com/{UPSTREAM_REPO}"
RAW_BASE = f"https://raw.githubusercontent.com/{UPSTREAM_REPO}"
API_COMMIT = f"https://api.github.com/repos/{UPSTREAM_REPO}/commits"

# Stable release identity shown in the picker. The default ref is the
# published 2.0 tag so the vendored bytes match this release metadata.
# Pass ``--ref master`` explicitly to test the latest upstream state.
DEFAULT_REF = "v2.0"
RELEASE = "PHOIBLE 2.0"
RELEASE_DATE = "2019-04-03"
LICENSE = "GPL-3.0 (codebase) + CC BY-SA 3.0 (data)"
CITATION = (
    "Moran, Steven & McCloy, Daniel (eds.) 2019. "
    "PHOIBLE 2.0. Jena: Max Planck Institute for the Science of "
    "Human History. http://phoible.org. "
    "DOI: 10.5281/zenodo.2626687"
)

# Upstream path -> vendored gzip filename. These two files are exactly
# what bake_phoible.py consumes.
FILES = {
    "data/phoible.csv": "phoible.csv.gz",
    "mappings/InventoryID-Bibtex.csv": "InventoryID-Bibtex.csv.gz",
}

_USER_AGENT = "phono-feature-phoible-refresh"


class FileMetadata(TypedDict):
    upstream_path: str
    raw_bytes: int
    gz_bytes: int
    raw_sha256: str
    gz_sha256: str


class Provenance(TypedDict):
    upstream: str
    ref: str
    commit: str
    release: str
    release_date: str
    license: str
    citation: str
    fetched_utc: str
    files: dict[str, FileMetadata]


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
        return resp.read()


def _resolve_commit(ref: str) -> str:
    """Resolve a ref (branch/tag/sha) to a full commit sha.

    The sha is what makes a refresh reproducible: record it, and a
    later ``--ref <sha>`` re-fetches the identical bytes.
    """
    raw = _fetch(f"{API_COMMIT}/{ref}")
    loaded = json.loads(raw)
    commit = loaded.get("sha")
    if not isinstance(commit, str) or not commit:
        raise RuntimeError(
            f"GitHub commit API did not return a sha for {ref!r}"
        )
    return commit


def _gzip_deterministic(data: bytes) -> bytes:
    """Gzip ``data`` at level 9 with a fixed mtime so identical input
    yields byte-identical output (stable diffs, no build-id churn)."""
    import io

    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as gz:
        gz.write(data)
    return buf.getvalue()


def update(ref: str) -> int:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    commit = _resolve_commit(ref)
    files_meta: dict[str, FileMetadata] = {}

    for upstream_path, out_name in FILES.items():
        url = f"{RAW_BASE}/{commit}/{upstream_path}"
        print(f"update_phoible: fetching {url}")
        raw = _fetch(url)
        gz_bytes = _gzip_deterministic(raw)
        (CACHE_DIR / out_name).write_bytes(gz_bytes)
        files_meta[out_name] = {
            "upstream_path": upstream_path,
            "raw_bytes": len(raw),
            "gz_bytes": len(gz_bytes),
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "gz_sha256": hashlib.sha256(gz_bytes).hexdigest(),
        }
        print(f"  -> {out_name} ({len(raw):,} raw -> {len(gz_bytes):,} gz)")

    provenance: Provenance = {
        "upstream": UPSTREAM_URL,
        "ref": ref,
        "commit": commit,
        "release": RELEASE,
        "release_date": RELEASE_DATE,
        "license": LICENSE,
        "citation": CITATION,
        "fetched_utc": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "files": files_meta,
    }
    PROVENANCE_PATH.write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"update_phoible: wrote {PROVENANCE_PATH.name} (commit {commit})")
    print(
        "update_phoible: now run `python web/scripts/bake_phoible.py` "
        "and `cd shared && pytest` to regenerate + verify."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ref",
        default=DEFAULT_REF,
        help=(
            f"Upstream git ref (branch, tag, or commit sha) to fetch. "
            f"Default {DEFAULT_REF!r} reproduces the published PHOIBLE "
            f"2.0 release; pass 'master' to fetch latest upstream, or "
            f"a commit sha to reproduce an exact past state."
        ),
    )
    args = parser.parse_args()
    try:
        return update(args.ref)
    except Exception as exc:  # noqa: BLE001 - surface a clean CLI error
        sys.stderr.write(f"update_phoible: failed: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
