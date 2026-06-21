"""Layer-boundary enforcement for ``chart.vowel_geometry``.

The package exists to make the vowel chart's conceptual layers
structural: display-slot semantics and box math must not know about
the outline, the outline must not know about cells, labels must not
read cell positions, and only the pipeline may relate boxes to the
outline. These tests parse the source (AST, no imports of the
modules under test) and fail with the offending edge named, so a
future change that quietly couples two layers breaks here instead
of resurfacing as the next buttons-escape-the-outline bug.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHART_DIR = _REPO_ROOT / "shared" / "src" / "phonology_shared" / "chart"
_PKG_DIR = _CHART_DIR / "vowel_geometry"
_PKG_PREFIX = "phonology_shared.chart.vowel_geometry"

#: Allowed intra-package import edges. A module may import only from
#: the layers listed here (plus anything OUTSIDE the package, which
#: these tests do not police).
_ALLOWED_EDGES: dict[str, frozenset[str]] = {
    "model": frozenset(),
    "display_slots": frozenset({"model"}),
    "cell_boxes": frozenset({"model", "display_slots"}),
    "outline": frozenset({"model"}),
    "furniture": frozenset({"model", "outline", "display_slots"}),
    "pipeline": frozenset(
        {"model", "display_slots", "cell_boxes", "outline", "furniture"}
    ),
}


def _package_modules() -> dict[str, ast.Module]:
    out: dict[str, ast.Module] = {}
    for path in sorted(_PKG_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        out[path.stem] = ast.parse(path.read_text(encoding="utf-8"))
    return out


def _intra_package_imports(
    tree: ast.Module,
) -> list[tuple[str, tuple[str, ...]]]:
    """``(target_module, imported_names)`` for every import of a
    sibling ``vowel_geometry`` module."""
    edges: list[tuple[str, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            module = node.module
            if module.startswith(_PKG_PREFIX + "."):
                target = module.removeprefix(_PKG_PREFIX + ".").split(".")[0]
                names = tuple(alias.name for alias in node.names)
                edges.append((target, names))
            elif module == _PKG_PREFIX:
                edges.append(("__init__", ()))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(_PKG_PREFIX):
                    target = alias.name.removeprefix(_PKG_PREFIX).lstrip(".")
                    edges.append((target.split(".")[0] or "__init__", ()))
    return edges


def test_layer_imports_respect_dependency_rules() -> None:
    modules = _package_modules()
    assert set(modules) >= {
        "model",
        "display_slots",
        "cell_boxes",
        "outline",
        "furniture",
        "pipeline",
    }
    for name, tree in modules.items():
        allowed = _ALLOWED_EDGES.get(name)
        assert allowed is not None, (
            f"vowel_geometry/{name}.py is not in the layer table; add it "
            f"to _ALLOWED_EDGES with its allowed dependencies"
        )
        for target, _names in _intra_package_imports(tree):
            assert target != "__init__", (
                f"vowel_geometry/{name}.py imports the package "
                f"__init__; import the owning module directly"
            )
            assert target in allowed, (
                f"forbidden layer edge: vowel_geometry/{name}.py imports "
                f"vowel_geometry/{target}.py. Allowed targets for "
                f"{name}: {sorted(allowed) or 'none'}. See the package "
                f"docstring for the layer table."
            )


def _identifiers(tree: ast.Module) -> set[str]:
    """Every identifier the module's CODE references: names,
    attribute tails, and imported symbols. Docstrings and comments
    are constants / non-nodes, so a module may still EXPLAIN a
    forbidden name in prose."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                out.add(alias.asname or alias.name)
    return out


def test_outline_knows_nothing_about_cells() -> None:
    """The outline is the boundary authority; it must consume
    abstract width demands, never cell objects. Importing only the
    silhouette dataclass from ``model`` (and never referencing
    ``VowelChartCell``) is the symbol-level teeth for that rule."""
    modules = _package_modules()
    for target, names in _intra_package_imports(modules["outline"]):
        if target == "model":
            assert set(names) <= {"VowelChartSilhouette"}, (
                f"outline.py may import only VowelChartSilhouette from "
                f"model, found {sorted(names)}"
            )
    assert "VowelChartCell" not in _identifiers(modules["outline"]), (
        "outline.py references VowelChartCell; relating cells to the "
        "outline belongs in pipeline.py"
    )


def test_furniture_never_reads_cell_positions() -> None:
    """Labels and chrome anchor to rows + the outline only; cell
    positions must never leak into their placement (a label that
    follows a button drifts off the outline the moment the button
    is nudged or pair-shifted)."""
    tree = ast.parse((_PKG_DIR / "furniture.py").read_text(encoding="utf-8"))
    assert "VowelChartCell" not in _identifiers(tree), (
        "furniture.py references VowelChartCell; labels must be placed "
        "from rows + outline only, never from button positions"
    )


def test_vowels_module_does_not_import_rendering() -> None:
    """``vowels.py`` is the inference layer. It may import the
    coordinate foundation (``vowel_space``) but must NOT import the
    rendering package (``vowel_geometry``) or the deleted compat
    facade (``vowels_layout``): inference sits BELOW rendering, so an
    upward import would invert the layering (it once forced a lazy
    ``__getattr__`` shim to dodge the resulting circular import)."""
    tree = ast.parse((_CHART_DIR / "vowels.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "vowels_layout" not in node.module
            assert "vowel_geometry" not in node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert "vowels_layout" not in alias.name
                assert "vowel_geometry" not in alias.name


def test_vowel_space_is_foundational() -> None:
    """``vowel_space`` is the low coordinate-system layer that both
    the inference module (``vowels``) and the rendering package
    (``vowel_geometry``) sit on, so it must import NOTHING from them
    or from ``consonants``. It depends only outward, on the
    presentation pixel constants its anchors are derived from. An
    import from a higher layer here would re-create the inverted
    dependency this whole split exists to remove."""
    tree = ast.parse(
        (_CHART_DIR / "vowel_space.py").read_text(encoding="utf-8")
    )
    forbidden = {"vowels", "vowel_geometry", "consonants"}
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
    for module in modules:
        assert "vowel_geometry" not in module, (
            f"vowel_space.py imports {module!r}; the foundation layer "
            f"must not depend on the rendering package"
        )
        assert module.split(".")[-1] not in forbidden, (
            f"vowel_space.py imports {module!r}; the foundation layer "
            f"must not depend on inference or grouping"
        )
