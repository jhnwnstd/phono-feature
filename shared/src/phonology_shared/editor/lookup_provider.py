"""Static-table-backed :py:class:`FeatureProvider` for the web bundle.

The web app cannot pull in pandas + numpy + panphon at runtime
(~120 MB uncompressed dependency tree); this provider substitutes a
JSON snapshot of PanPhon's IPA-to-features table baked at desktop
build time. Wire-compatible with the desktop's live
:py:class:`PanPhonFeatureProvider` for every segment present in the
snapshot, which is every entry in PanPhon's ``ipa_all.csv``.

The snapshot file ships alongside this module
(``_panphon_table.generated.json``). It is gitignored: the build
pipeline regenerates it from the installed ``panphon`` package via
:py:mod:`web.scripts.bake_panphon` before zipping the shared/
package for the Pyodide bundle.

Compact encoding: each segment maps to a single string whose i-th
character is the feature value for ``feature_names[i]``. See
:py:mod:`web.scripts.bake_panphon` for the producer side.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from importlib import resources
from pathlib import Path
from typing import Any

from phonology_shared.editor.providers import (
    GeneratedInventory,
    prune_unused_features,
    restrict_bundles,
)

# Filename of the build-baked snapshot. Co-located with this module
# so Pyodide's importlib.resources lookup works against the package
# even when shared/ is zip-mounted.
_TABLE_FILENAME = "_panphon_table.generated.json"


class LookupTableNotAvailable(RuntimeError):
    """Raised at construction when the baked JSON is missing.

    The web bundle ships the file unconditionally; this only fires
    on a stale developer checkout where ``web/scripts/bake_panphon``
    has never run. The runtime registry catches this and excludes
    the provider from the available list so the UI gracefully
    falls back to static presets.
    """


def _load_table_bytes() -> bytes:
    """Return the snapshot bytes from the package's data files.

    Uses :py:func:`importlib.resources.files` so the lookup works
    against an editable install, a zip-mounted bundle, AND a
    Pyodide virtual filesystem mount; a plain ``open()`` would
    break the Pyodide path.
    """
    pkg = resources.files("phonology_shared.editor")
    target = pkg / _TABLE_FILENAME
    try:
        return target.read_bytes()
    except OSError as exc:
        # OSError covers FileNotFoundError (stale checkout without
        # the bake step) plus PermissionError and the zipimport
        # "member not found" path the Pyodide bundle goes through.
        raise LookupTableNotAvailable(
            f"baked PanPhon table not found at {_TABLE_FILENAME}; "
            f"run `python web/scripts/bake_panphon.py` to produce it "
            f"(originating error: {exc})"
        ) from exc


class LookupFeatureProvider:
    """Look up segment feature bundles in the baked snapshot.

    Implements
    :py:class:`phonology_shared.editor.providers.FeatureProvider`.
    The shipped snapshot covers every IPA string PanPhon's
    ``ipa_all.csv`` knows about (~6.4k entries); segments outside
    that set land in :py:attr:`GeneratedInventory.unresolved`
    exactly as the desktop's live provider would for an unknown
    glyph.
    """

    name: str = "PanPhon"

    def __init__(
        self,
        table: Mapping[str, Any] | None = None,
    ) -> None:
        """Construct from a pre-loaded table dict (testing /
        in-memory override) or from the packaged JSON snapshot.

        Eager-decodes the snapshot once so per-call lookup is a
        single dict access; with ~6.4k entries the upfront cost is
        well under a millisecond and removes the per-segment json-
        parse cost the dialog's live-preview would otherwise incur.
        """
        if table is None:
            raw = _load_table_bytes()
            table = json.loads(raw)
        if not isinstance(table, Mapping):
            raise TypeError(
                f"PanPhon lookup table must be a mapping at top "
                f"level; got {type(table).__name__}"
            )

        self.version: str = str(table.get("provider_version", "unknown"))
        feature_names = table.get("feature_names")
        if not isinstance(feature_names, list) or not all(
            isinstance(n, str) for n in feature_names
        ):
            raise ValueError(
                "PanPhon lookup table is missing a 'feature_names' "
                "list-of-strings; rerun bake_panphon to regenerate"
            )
        self._feature_names: tuple[str, ...] = tuple(feature_names)

        segments = table.get("segments")
        if not isinstance(segments, Mapping):
            raise ValueError(
                "PanPhon lookup table is missing a 'segments' object; "
                "rerun bake_panphon to regenerate"
            )
        # Pre-build per-segment bundles. Encoding is positional: each
        # value is a single-character slice indexed by feature_names.
        # Building once at __init__ avoids re-zipping on every
        # preview-debounce tick the dialog fires.
        n = len(self._feature_names)
        self._bundles: dict[str, Mapping[str, str]] = {}
        for ipa, encoded in segments.items():
            if not isinstance(ipa, str) or not isinstance(encoded, str):
                continue
            if len(encoded) != n:
                # Skip rather than raise so a forward-compat snapshot
                # with extra columns doesn't crash a behind-the-tip
                # runtime; the unresolved counter will surface the
                # gap to the user.
                continue
            self._bundles[ipa] = dict(zip(self._feature_names, encoded))

    @classmethod
    def from_path(cls, path: str | Path) -> LookupFeatureProvider:
        """Construct from a JSON file at an arbitrary path.

        Convenience entry point for tests that ship their own
        stub table; production callers use the no-arg constructor
        which reads the packaged snapshot.
        """
        with Path(path).open("r", encoding="utf-8") as f:
            return cls(table=json.load(f))

    def display_label(self) -> str:
        # Matches the desktop's live PanPhonFeatureProvider so the
        # dropdown reads identically across clients.
        return self.name

    def feature_names(self) -> tuple[str, ...]:
        """Canonical feature list this provider emits.

        Matches the desktop's live provider verbatim (the bake
        script preserves PanPhon's column order through the app-
        name mapping) so a user switching clients mid-project sees
        the same column set in both grids.
        """
        return self._feature_names

    def generate(self, segments: list[str]) -> GeneratedInventory:
        """Resolve ``segments`` to feature bundles via the lookup.

        Matches the desktop's
        :py:meth:`PanPhonFeatureProvider.generate` behaviour for
        the unresolved-feature-pruning step: features that no
        resolved segment specifies (every value is ``"0"``) are
        dropped from the returned ``features`` tuple and from every
        per-segment bundle. The full feature set is still surfaced
        when no segment resolves (so the user has columns to edit
        on the failure path) or when the input list is empty.
        """
        features: tuple[str, ...] = self._feature_names
        resolved: dict[str, Mapping[str, str]] = {}
        unresolved: list[str] = []
        warnings: list[str] = []

        for symbol in segments:
            bundle = self._bundles.get(symbol)
            if bundle is None:
                unresolved.append(symbol)
                warnings.append(
                    f"{symbol!r}: not in the PanPhon table; "
                    "edit the column by hand or remove it."
                )
                continue
            # Copy so a downstream mutation can't leak into the
            # shared lookup. The bundle is small (~24 entries) so
            # the copy is a non-issue.
            resolved[symbol] = dict(bundle)

        if resolved:
            features = prune_unused_features(features, resolved)
            resolved = restrict_bundles(resolved, features)

        return GeneratedInventory(
            features=features,
            segments=resolved,
            unresolved=tuple(unresolved),
            warnings=tuple(warnings),
        )
