# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Required Notice: Copyright 2026 John Winstead,
# https://github.com/jhnwnstd/phono-feature
"""Canonical set of hand-authored web JavaScript sources.

Lives in its own importable module (not conftest.py) for the same
reason as :py:mod:`_inventory_names`: tests want the list at
import time, and pytest's conftest.py is not a regular module, so
importing constants from it across files fails.

DISCOVERED, not hand-listed. ``web/main.js`` used to be the entire
frontend, so every parity test that extracts a span out of the JS
hard-coded that one path. The entry point now only orders the startup
sequence and the app lives in ``web/js/``, which means a single-path
read matches nothing. Two of the three readers failed loudly when the
split landed; the third greps for ``cell.<name>`` reads and asserts
nothing unexpected appears, so an empty read set passed VACUOUSLY.
That is the failure mode this module exists to remove: glob the set,
and pin it non-empty so a moved directory is a red test rather than a
quiet one.
"""

from __future__ import annotations

import re
from pathlib import Path

_WEB_DIR = Path(__file__).resolve().parents[2] / "web"

#: The ES module entry point. Loaded by ``index.html`` with
#: ``<script type="module">``; it imports everything under ``js/``.
WEB_JS_ENTRY = _WEB_DIR / "main.js"

#: Directory holding the entry point's import graph.
WEB_JS_MODULE_DIR = _WEB_DIR / "js"

#: Every hand-authored web JS source, entry point first then the
#: modules in name order. ``sw.js`` is deliberately absent: it is a
#: separate classic script with no share in the Python mirror, so a
#: parity grep over it would only add noise.
WEB_JS_SOURCES: tuple[Path, ...] = (
    WEB_JS_ENTRY,
    *sorted(WEB_JS_MODULE_DIR.glob("*.js")),
)

#: All of the above concatenated, for greps that only need to count
#: or collect occurrences. Each file keeps its own line structure, so
#: ``re.MULTILINE`` anchors still behave per source line.
WEB_JS_TEXT = "\n".join(
    path.read_text(encoding="utf-8") for path in WEB_JS_SOURCES
)


def extract_web_js(pattern: str) -> str:
    """Pull one source span out of the web JS sources, or fail with a
    message naming what went missing.

    Searched per FILE rather than over the concatenation so a
    ``re.DOTALL`` pattern can never match across a file boundary and
    silently return a span that exists in no single source. A rename
    should update the calling test, not quietly match nothing.
    """
    for path in WEB_JS_SOURCES:
        match = re.search(pattern, path.read_text(encoding="utf-8"), re.DOTALL)
        if match is not None:
            return match.group(0)
    raise AssertionError(
        f"could not locate /{pattern}/ in any of "
        f"{[p.name for p in WEB_JS_SOURCES]}"
    )
