"""Package-level boundary enforcement for ``phonology_shared``.

CONTRIBUTING states three structural rules for the shared package.
Until now they were prose only, while the finer-grained vowel-geometry
layer table next door was machine-checked, so the coarse rules were the
easier ones to break. These tests close that gap. Like
:py:mod:`test_vowel_space_geometry_boundaries` they parse the source
(AST, no imports of the modules under test) and fail naming the
offending edge.

The rules, and why each is stated the way it is:

1. **No GUI toolkit anywhere in ``shared/``.** The whole package is
   mirrored into ``python_bundle.zip`` and imported under Pyodide,
   where ``PyQt6`` does not exist. A Qt import at any scope, even
   inside a function, is a latent web crash rather than a style
   problem, so this check does not care about scope. The browser-side
   equivalents (``js``, ``pyodide``) are barred too: they would break
   the desktop just as asymmetrically.

2. **``data/`` is the leaf at module scope.** Every import-time
   ``phonology_shared`` import inside ``data/`` must stay inside
   ``data/``.

3. **The acyclicity rule is module-level, not subpackage-level.**
   ``chart/`` and ``presentation/`` legitimately import each other
   (``chart/vowel_space.py`` reads pixel constants from
   ``presentation/layout.py``; ``presentation/view_models.py`` reads
   placement from ``chart/consonants.py``). That is legal because no
   individual MODULE sits on a cycle. Testing this at subpackage
   granularity would report a false violation and invite someone to
   "fix" a working design, so the graph is built over modules.

Rule 2 has two deliberate exceptions, the lazy reverse edges in
``data/inventory.py``. They are pinned exactly rather than merely
allowed, so a third one cannot appear unnoticed.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PKG_DIR = _REPO_ROOT / "shared" / "src" / "phonology_shared"
_PKG_ROOT = "phonology_shared"

#: Import roots that must never appear in ``shared/``, at any scope.
#: ``shared/`` runs on the desktop under CPython AND in the browser
#: under Pyodide; each of these exists in exactly one of the two.
_FORBIDDEN_ROOTS = frozenset(
    {
        "PyQt6",
        "PyQt5",
        "PySide2",
        "PySide6",
        "tkinter",
        "js",
        "pyodide",
    }
)

#: The only import-time ``phonology_shared`` imports ``data/`` may make
#: are into ``data/`` itself.
_DATA_SUBPACKAGE = "data"

#: The two deliberate lazy reverse edges out of ``data/`` and into
#: ``presentation/``, as ``(module, function, target)``. Both are
#: function-local and commented at the call site; see CONTRIBUTING.
#: Adding a third is a design decision, so it must edit this tuple.
_ALLOWED_LAZY_REVERSE_EDGES = frozenset(
    {
        (
            "data/inventory.py",
            "normalize_feature_key",
            "phonology_shared.presentation.feature_metadata",
        ),
        (
            "data/inventory.py",
            "from_grid",
            "phonology_shared.presentation.constants",
        ),
    }
)


def _module_name(path: Path) -> str:
    """Dotted module name for a file inside the package. A package
    ``__init__`` collapses onto the package name, so an import of the
    package and an import of its ``__init__`` are the same graph node."""
    rel = path.relative_to(_PKG_DIR.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _module_scope_imports(
    tree: ast.Module,
) -> list[ast.Import | ast.ImportFrom]:
    """Imports that run at IMPORT time: direct children of the module
    body plus any nested in module-level ``if`` / ``try`` / ``with``
    (``if TYPE_CHECKING:`` and optional-dependency guards both live
    there). Never anything inside a function or class body, which is
    what makes a lazy import lazy."""
    found: list[ast.Import | ast.ImportFrom] = []

    def visit(stmts: list[ast.stmt]) -> None:
        for stmt in stmts:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                found.append(stmt)
            elif isinstance(stmt, (ast.If, ast.Try, ast.With)):
                for attr in ("body", "orelse", "finalbody"):
                    visit(getattr(stmt, attr, []) or [])
                for handler in getattr(stmt, "handlers", []):
                    visit(handler.body)

    visit(tree.body)
    return found


def _sources() -> dict[str, Path]:
    return {_module_name(p): p for p in sorted(_PKG_DIR.rglob("*.py"))}


def _trees() -> dict[str, ast.Module]:
    return {
        name: ast.parse(path.read_text(encoding="utf-8"))
        for name, path in _sources().items()
    }


def _rel(path: Path) -> str:
    return str(path.relative_to(_PKG_DIR))


def _import_roots(node: ast.Import | ast.ImportFrom) -> set[str]:
    """Top-level package name(s) an import statement reaches for.
    A relative ``ImportFrom`` (``level > 0``) names no external root."""
    if isinstance(node, ast.Import):
        return {alias.name.split(".")[0] for alias in node.names}
    if node.level:
        return set()
    return {(node.module or "").split(".")[0]}


def test_package_source_set_is_nonempty() -> None:
    """Guard against the glob silently matching nothing after a layout
    change. Without this every test below would pass vacuously."""
    sources = _sources()
    assert len(sources) > 20, (
        f"only {len(sources)} modules found under {_PKG_DIR}; the "
        "boundary tests would pass vacuously."
    )


def test_shared_never_imports_a_gui_toolkit() -> None:
    """Rule 1. Scope-insensitive: a function-local ``import PyQt6`` in
    ``shared/`` still crashes the browser build the moment that function
    runs."""
    offenders: list[str] = []
    for name, tree in _trees().items():
        path = _sources()[name]
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            hits = _import_roots(node) & _FORBIDDEN_ROOTS
            for hit in sorted(hits):
                offenders.append(f"{_rel(path)}:{node.lineno} imports {hit}")
    assert not offenders, (
        "shared/ must stay framework-agnostic (it runs under Pyodide "
        "too); move this to desktop/src/phonology_features/gui/ or the "
        "web bridge:\n  " + "\n  ".join(offenders)
    )


def test_data_is_the_leaf_at_module_scope() -> None:
    """Rule 2. No import-time ``phonology_shared`` import inside
    ``data/`` may leave ``data/``."""
    offenders: list[str] = []
    for name, tree in _trees().items():
        path = _sources()[name]
        if path.relative_to(_PKG_DIR).parts[0] != _DATA_SUBPACKAGE:
            continue
        for node in _module_scope_imports(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            target = node.module or ""
            if not target.startswith(f"{_PKG_ROOT}."):
                continue
            subpackage = target.split(".")[1]
            if subpackage != _DATA_SUBPACKAGE:
                offenders.append(
                    f"{_rel(path)}:{node.lineno} -> {target} " "(module scope)"
                )
    assert not offenders, (
        "data/ is the leaf: everything may depend on it, it depends on "
        "nothing in the package. Make the import function-local and "
        "register it in _ALLOWED_LAZY_REVERSE_EDGES, or move the "
        "constant into data/:\n  " + "\n  ".join(offenders)
    )


def test_data_lazy_reverse_edges_are_exactly_the_documented_two() -> None:
    """Rule 2's exceptions, pinned. Equality (not a subset) so a new
    reverse edge fails here and has to be argued for in CONTRIBUTING,
    and so a retired one stops being advertised."""
    found: set[tuple[str, str, str]] = set()
    for name, tree in _trees().items():
        path = _sources()[name]
        if path.relative_to(_PKG_DIR).parts[0] != _DATA_SUBPACKAGE:
            continue
        module_scope = {id(n) for n in _module_scope_imports(tree)}
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(func):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if id(node) in module_scope:
                    continue
                target = node.module or ""
                if not target.startswith(f"{_PKG_ROOT}."):
                    continue
                if target.split(".")[1] == _DATA_SUBPACKAGE:
                    # Intra-data lazy import (inventory.parse ->
                    # data._parse) breaks a two-module cycle inside the
                    # leaf; it is not a reverse edge out of it.
                    continue
                found.add((_rel(path), func.name, target))
    assert found == _ALLOWED_LAZY_REVERSE_EDGES, (
        "the set of lazy reverse edges out of data/ changed.\n"
        f"  expected: {sorted(_ALLOWED_LAZY_REVERSE_EDGES)}\n"
        f"  found:    {sorted(found)}"
    )


def _module_import_graph() -> dict[str, set[str]]:
    """Import-time edges between modules of the package, resolved so a
    package import lands on the package node."""
    sources = _sources()
    graph: dict[str, set[str]] = {}
    for name, tree in _trees().items():
        targets: set[str] = set()
        for node in _module_scope_imports(tree):
            if isinstance(node, ast.ImportFrom):
                target = node.module or ""
                if not target.startswith(_PKG_ROOT):
                    continue
                if target in sources:
                    targets.add(target)
                    continue
                # ``from pkg import submodule`` names the submodule in
                # the alias list rather than in ``node.module``.
                for alias in node.names:
                    candidate = f"{target}.{alias.name}"
                    if candidate in sources:
                        targets.add(candidate)
            else:
                for alias in node.names:
                    if alias.name in sources:
                        targets.add(alias.name)
        graph[name] = targets - {name}
    return graph


def _find_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    """One cycle as the path that closes it, or ``None``. Iterative so a
    deep chain cannot hit the recursion limit."""
    state: dict[str, int] = {}
    for root in sorted(graph):
        if state.get(root):
            continue
        path: list[str] = []
        # (node, whether this visit is the post-order pass)
        stack: list[tuple[str, bool]] = [(root, False)]
        while stack:
            node, leaving = stack.pop()
            if leaving:
                state[node] = 2
                path.pop()
                continue
            if state.get(node) == 2:
                continue
            state[node] = 1
            path.append(node)
            stack.append((node, True))
            for nxt in sorted(graph.get(node, ()), reverse=True):
                if state.get(nxt) == 1:
                    return path[path.index(nxt) :] + [nxt]
                if state.get(nxt) != 2:
                    stack.append((nxt, False))
    return None


def test_module_level_import_graph_is_acyclic() -> None:
    """Rule 3, the real invariant. ``chart`` and ``presentation`` import
    each other at SUBPACKAGE granularity and that is fine; what must
    never happen is a MODULE sitting on an import-time cycle."""
    cycle = _find_cycle(_module_import_graph())
    assert cycle is None, (
        "import-time module cycle in phonology_shared:\n  "
        + " -> ".join(m.removeprefix(f"{_PKG_ROOT}.") for m in cycle or [])
        + "\nBreak it by moving the shared constant down a layer, or "
        "make one edge function-local and comment why."
    )


def test_chart_and_presentation_are_mutually_dependent_subpackages() -> None:
    """Pins the thing rule 3 exists to tolerate, so nobody "fixes" it.

    If this ever fails because the mutual edge is GONE, that is fine:
    delete this test and simplify the CONTRIBUTING note. It fails
    loudly rather than silently to keep the docs and the code honest.
    """
    graph = _module_import_graph()

    def subpackage(module: str) -> str:
        parts = module.split(".")
        return parts[1] if len(parts) > 1 else ""

    edges = {
        (subpackage(src), subpackage(dst))
        for src, dsts in graph.items()
        for dst in dsts
        if subpackage(src) != subpackage(dst)
    }
    assert ("chart", "presentation") in edges, edges
    assert ("presentation", "chart") in edges, edges
