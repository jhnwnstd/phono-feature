# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Required Notice: Copyright 2026 John Winstead,
# https://github.com/jhnwnstd/phono-feature
"""Verify (or insert) the SPDX license header in every source file.

Check mode (default) exits nonzero listing each file whose first
few lines lack the ``SPDX-License-Identifier`` line or the Required
Notice, so CI fails the same way it does for any other lint error.
``--fix`` inserts the header instead: after a shebang if present,
otherwise at the very top, using the comment syntax of the file
type. Both modes cover the distributed source surface only: the
three packages' ``src`` trees, ``web/scripts``, and the web app's
JS/CSS entry files. Tests, generated ``dist`` output, and vendored
caches are out of scope (generated CSS gets its header from the
``build.py`` emitters; the bundle zip ships LICENSE + NOTICE
alongside the sources).

Run from the repo root::

    python tools/check_license_headers.py          # verify
    python tools/check_license_headers.py --fix    # insert
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SPDX_ID = "SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0"
NOTICE = (
    "Required Notice: Copyright 2026 John Winstead,",
    "https://github.com/jhnwnstd/phono-feature",
)

#: Directories swept for ``*.py`` files.
PY_TREES = (
    "shared/src",
    "desktop/src",
    "web/src",
    "web/scripts",
    "tools",
)

#: Individual JS / CSS entry files that ship to visitors.
WEB_FILES = ("web/main.js", "web/sw.js", "web/style.css")

#: Vendored caches under the swept trees that carry their own
#: upstream licenses.
EXCLUDED_PARTS = ("font_cache", "phoible_cache", "__pycache__")


def _py_header() -> str:
    return f"# {SPDX_ID}\n" f"# {NOTICE[0]}\n" f"# {NOTICE[1]}\n"


def _js_header() -> str:
    return f"// {SPDX_ID}\n// {NOTICE[0]} {NOTICE[1]}\n"


def _css_header() -> str:
    return f"/* {SPDX_ID}\n   {NOTICE[0]} {NOTICE[1]} */\n"


def _targets() -> list[Path]:
    files: list[Path] = []
    for tree in PY_TREES:
        for path in sorted((ROOT / tree).rglob("*.py")):
            if any(part in EXCLUDED_PARTS for part in path.parts):
                continue
            files.append(path)
    files.extend(ROOT / name for name in WEB_FILES)
    return files


def _has_header(path: Path) -> bool:
    try:
        head = path.read_text(encoding="utf-8")[:512]
    except OSError:
        return False
    return SPDX_ID in head and NOTICE[0] in head


def _insert(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        header = _py_header()
    elif path.suffix == ".js":
        header = _js_header()
    else:
        header = _css_header()
    if text.startswith("#!"):
        shebang, _, rest = text.partition("\n")
        text = f"{shebang}\n{header}{rest}"
    else:
        text = header + text
    path.write_text(text, encoding="utf-8")


#: Member packages that carry real COPIES of the root LICENSE and
#: NOTICE (copies, not symlinks: a Windows checkout without symlink
#: privilege, a GitHub ZIP download, or a member directory copied
#: out of the monorepo materializes a symlink as a one-line path
#: string, and a wheel built from that state ships no terms). This
#: check is the drift guard that makes the copies safe.
MEMBER_DIRS = ("shared", "desktop", "web")


def _stale_copies() -> list[Path]:
    stale: list[Path] = []
    for name in ("LICENSE", "NOTICE"):
        root_bytes = (ROOT / name).read_bytes()
        for member in MEMBER_DIRS:
            copy = ROOT / member / name
            if not copy.is_file() or copy.read_bytes() != root_bytes:
                stale.append(copy)
    return stale


def main() -> int:
    fix = "--fix" in sys.argv[1:]
    missing = [p for p in _targets() if not _has_header(p)]
    stale = _stale_copies()
    if fix:
        for path in missing:
            _insert(path)
            print(f"header added: {path.relative_to(ROOT)}")
        for copy in stale:
            copy.write_bytes((ROOT / copy.name).read_bytes())
            print(f"copy refreshed: {copy.relative_to(ROOT)}")
        print(f"{len(missing)} header(s) inserted, {len(stale)} copies")
        return 0
    bad = False
    for path in missing:
        bad = True
        print(
            f"missing license header: {path.relative_to(ROOT)}",
            file=sys.stderr,
        )
    for copy in stale:
        bad = True
        print(
            f"license copy out of sync with root: "
            f"{copy.relative_to(ROOT)}",
            file=sys.stderr,
        )
    if bad:
        return 1
    print(
        f"license headers ok ({len(_targets())} files); "
        f"member LICENSE/NOTICE copies in sync"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
