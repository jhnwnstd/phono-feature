# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Required Notice: Copyright 2026 John Winstead,
# https://github.com/jhnwnstd/phono-feature
"""Layer gate for the web frontend's ES module graph.

The Python side of this repo has its package rules machine-checked
(:py:mod:`test_package_boundaries`), but the frontend was one
6,660-line ``web/main.js`` with no internal boundaries at all, so
there was nothing to check. It is now an entry point plus the modules
under ``web/js/``, and this file holds that structure to the same
standard: the import graph is acyclic apart from one PINNED mutual
pair, and the module every other module reads at init time is a leaf.

Why those two rules and not a hand-written tier table: they are the
two properties the split actually depends on.

* **Acyclicity, with one pinned exception.** ES modules tolerate
  cycles, so a cycle is not a load error; it is a latent
  temporal-dead-zone bug that only bites when a member reads another
  member's binding during module evaluation. Keeping the graph a DAG
  means the question never arises. The one exception is real
  mutuality rather than an accident, so it is pinned by EQUALITY: a
  second pair has to be argued for here, and the existing pair cannot
  be "fixed" away by someone who reads a cycle as a defect.
* **The init-time leaf.** Every module-init read that crosses a module
  boundary resolves in ``config.js`` (the frozen tables ``build.py``
  bakes into ``index.html``). That is exactly the shape a cycle would
  turn into a TDZ crash, so ``config.js`` importing nothing is what
  keeps those reads safe no matter how the rest of the graph moves.

Mirrors the Python gate's reading of acyclicity: ask whether THIS
MODULE now sits on a cycle, not whether its neighbourhood looks
tidy.
"""

from __future__ import annotations

import re
from pathlib import Path

from _web_sources import (
    WEB_JS_ENTRY,
    WEB_JS_MODULE_DIR,
    WEB_JS_SOURCES,
)

#: The one mutual pair the graph is allowed to carry, as a frozenset
#: so the assertion is direction-blind. A segment click runs an
#: analysis and an analysis relayouts the segment grid; both crossings
#: are calls made after boot, never module-init reads, so the cycle
#: carries no TDZ risk. Pinned by equality: see the module docstring.
_PINNED_MUTUAL_PAIRS = frozenset({frozenset({"segments", "analysis"})})

#: Modules that must import nothing. ``config.js`` because every
#: cross-module init-time read lands there; ``env.js`` because it is
#: the side-effect module whose two IIFEs have to run before any
#: module body reads a Houdini-registered CSS token.
_REQUIRED_LEAVES = frozenset({"config", "env"})

#: Start of a top-level ``import`` or ``export`` declaration. Anchored
#: to the line start because an ES module's declarations are top-level;
#: a multi-line ``import {`` block matches once, on its first line.
_DECL_START_RE = re.compile(r"(?m)^[ \t]*(?P<kw>import|export)\b(?!\s*\()")

#: ``from "spec"`` or a bare ``import "spec"``, in either quote style.
_SOURCE_RE = re.compile(
    r"""(?:\bfrom\s*|\bimport\s*)(?P<q>['"])(?P<spec>[^'"]+)(?P=q)""",
    re.DOTALL,
)

#: A dynamic ``import(...)``. Matched separately because it is an
#: expression, not a declaration, and a computed specifier cannot be
#: resolved statically at all.
_DYNAMIC_RE = re.compile(
    r"""\bimport\s*\(\s*(?:(?P<q>['"])(?P<spec>[^'"]+)(?P=q))?""",
    re.DOTALL,
)


class UnparseableImport(Exception):
    """An import this gate cannot resolve into a graph edge.

    Raised rather than skipped. The original gate matched only
    ``import "x";`` and ``import { a } from "x";`` with a double-quoted
    specifier, and SILENTLY returned no edge for a default import, a
    namespace import, a mixed import, a re-export, a single-quoted
    specifier or a dynamic import. An unseen edge is an unseen cycle:
    adding ``import * as seg from "./segments.js"`` to ``config.js``
    put ``config`` inside a real cycle while all five tests below
    stayed green. Blindness that reads as success is worse than no
    gate, so anything unresolvable now fails loudly.
    """


def _module_name(path: Path) -> str:
    """``web/js/segments.js`` -> ``segments``; the entry is ``main``."""
    return path.stem


def _imports_of(path: Path) -> list[str]:
    """Module names imported by ``path``, covering every import form.

    Specifiers are relative and always name a ``.js`` file, so the
    basename is the module name. The entry writes ``./js/x.js`` while
    the modules write ``./x.js``; both reduce the same way.

    Walks declarations rather than pattern-matching the two forms the
    codebase happens to use, so a form nobody has written yet still
    produces an edge. A declaration whose source cannot be read raises
    :py:class:`UnparseableImport`.
    """
    text = path.read_text(encoding="utf-8")
    specs: list[str] = []

    for match in _DECL_START_RE.finditer(text):
        end = text.find(";", match.end())
        body = text[match.start() : end if end != -1 else len(text)]
        source = _SOURCE_RE.search(body)
        if source is not None:
            specs.append(source.group("spec"))
            continue
        if match.group("kw") == "export":
            # A local export (``export function f`` / ``export const X``)
            # names no source, so it is not an edge.
            continue
        raise UnparseableImport(
            f"{path.name}: cannot read a module specifier out of "
            f"{body.strip()[:90]!r}. Every import must resolve to an "
            f"edge or this gate is blind to it."
        )

    for match in _DYNAMIC_RE.finditer(text):
        if match.group("spec") is None:
            raise UnparseableImport(
                f"{path.name}: dynamic import with a non-literal "
                f"specifier cannot be resolved statically, so the "
                f"layer graph cannot account for it."
            )
        # A literal dynamic specifier is a real edge, deferred or not.
        specs.append(match.group("spec"))

    return [Path(spec).stem for spec in specs]


def _graph() -> dict[str, set[str]]:
    return {
        _module_name(path): set(_imports_of(path)) for path in WEB_JS_SOURCES
    }


def _sccs(graph: dict[str, set[str]]) -> list[set[str]]:
    """Strongly-connected components with more than one member.

    Iterative Tarjan: the graph is small but recursion depth is a
    needless failure mode in a test.
    """
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    out: list[set[str]] = []
    counter = 0

    for root in graph:
        if root in index:
            continue
        work: list[tuple[str, list[str]]] = [
            (root, sorted(graph.get(root, ())))
        ]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, pending = work[-1]
            if pending:
                nxt = pending.pop()
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, sorted(graph.get(nxt, ()))))
                elif nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                component: set[str] = set()
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.add(member)
                    if member == node:
                        break
                if len(component) > 1:
                    out.append(component)
    return out


def test_web_js_source_set_is_nonempty() -> None:
    """The globbed source set must actually find the frontend.

    Every other test here greps that set, and a grep over nothing
    passes. This is the same guard shape as
    ``test_package_source_set_is_nonempty`` on the Python side.
    """
    assert WEB_JS_ENTRY.is_file(), f"missing entry point {WEB_JS_ENTRY}"
    assert (
        WEB_JS_MODULE_DIR.is_dir()
    ), f"missing module directory {WEB_JS_MODULE_DIR}"
    modules = [p for p in WEB_JS_SOURCES if p != WEB_JS_ENTRY]
    assert len(modules) >= 10, (
        f"found only {len(modules)} modules under {WEB_JS_MODULE_DIR}; "
        f"the frontend split produced 15, so this set is wrong"
    )


def test_every_import_specifier_resolves() -> None:
    """No module imports a file that is not on disk.

    The browser would surface this as a 404 at boot, which the
    Playwright smoke catches; catching it here names the offending
    specifier instead of a blank page.
    """
    known = {_module_name(p) for p in WEB_JS_SOURCES}
    missing: dict[str, set[str]] = {}
    for path in WEB_JS_SOURCES:
        unresolved = set(_imports_of(path)) - known
        if unresolved:
            missing[path.name] = unresolved
    assert not missing, f"import specifiers resolve to nothing: {missing}"


def test_no_module_imports_the_entry_point() -> None:
    """``main.js`` only orders the startup sequence.

    Nothing may import it, so the entry stays the single place the
    boot order is stated and the module graph below it has one root.
    """
    importers = sorted(
        _module_name(path)
        for path in WEB_JS_SOURCES
        if "main" in _imports_of(path)
    )
    assert not importers, (
        f"{importers} import the entry point; move the shared symbol "
        f"down into a module both sides can import instead"
    )


def test_required_leaves_import_nothing() -> None:
    """``config.js`` and ``env.js`` sit below everything else.

    See the module docstring: ``config`` is where every cross-module
    module-init read resolves, so it has to be unreachable from a
    cycle, and ``env`` has to evaluate before any module body.
    """
    graph = _graph()
    for leaf in sorted(_REQUIRED_LEAVES):
        assert leaf in graph, f"{leaf}.js is gone from the module set"
        assert not graph[leaf], (
            f"{leaf}.js now imports {sorted(graph[leaf])}; it is "
            f"required to stay a leaf so init-time reads of it can "
            f"never land inside an import cycle"
        )


def test_module_graph_is_acyclic_apart_from_the_pinned_pair() -> None:
    """Pinned by EQUALITY, not by subset.

    A new cycle fails here, and so does removing the existing one: the
    ``segments`` / ``analysis`` mutuality is deliberate, so anyone
    reading it as a defect has to change this pin and say why.
    """
    components = [frozenset(c) for c in _sccs(_graph())]
    assert set(components) == _PINNED_MUTUAL_PAIRS, (
        f"module cycles changed.\n"
        f"  found:  {sorted(sorted(c) for c in components)}\n"
        f"  pinned: {sorted(sorted(c) for c in _PINNED_MUTUAL_PAIRS)}\n"
        f"A new cycle means two modules now call into each other; "
        f"move the shared symbol into a lower module instead. If the "
        f"mutuality is genuine, widen this pin and record why."
    )
