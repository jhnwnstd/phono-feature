"""PanPhon-backed implementation of
:py:class:`phonology_shared.editor.providers.FeatureProvider`.

The desktop New-inventory dialog calls
:py:meth:`PanPhonFeatureProvider.generate` to bootstrap a feature
grid from IPA segment symbols. PanPhon's ``FeatureTable.word_fts``
returns a list of ``Segment`` objects per input string; we accept
only single-segment resolutions to keep the result deterministic.
Symbols that parse as zero or multiple PanPhon segments (the
tie-bar / affricate / unknown-glyph failure mode) land in
:py:attr:`GeneratedInventory.unresolved` with a human-readable
warning, never in the resolved bundle.

The PanPhon import is lazy (inside :py:meth:`__init__`); the
registry in
:py:mod:`phonology_features.providers` probes module availability
with :py:func:`importlib.util.find_spec` before constructing.
"""

from __future__ import annotations

import importlib.metadata
from collections.abc import Mapping

from phonology_shared.editor.panphon_features import (
    PANPHON_TO_APP_FEATURE,
    panphon_value_to_app,
)
from phonology_shared.editor.providers import (
    GeneratedInventory,
    prune_unused_features,
    restrict_bundles,
)


def _segment_to_bundle(
    seg_obj: object, panphon_names: list[str]
) -> dict[str, str]:
    """Convert a single PanPhon ``Segment`` to a per-feature bundle
    keyed by app feature names.

    Iterates :py:attr:`FeatureTable.names` so the value vector lines
    up positionally even when PanPhon adds new columns; unknown
    panphon names (not in :py:data:`PANPHON_TO_APP_FEATURE`) are
    skipped silently so a future PanPhon release does not crash the
    desktop. The corresponding bundle stays consistent with what
    :py:meth:`PanPhonFeatureProvider.feature_names` advertises.
    """
    if hasattr(seg_obj, "strings"):
        values = list(seg_obj.strings())
    elif hasattr(seg_obj, "numeric"):
        values = list(seg_obj.numeric())
    else:
        raise TypeError(
            "Unsupported PanPhon Segment object: missing strings/numeric"
        )
    if len(values) != len(panphon_names):
        raise ValueError(
            f"PanPhon returned {len(values)} values for "
            f"{len(panphon_names)} feature names"
        )
    bundle: dict[str, str] = {}
    for panphon_name, value in zip(panphon_names, values, strict=False):
        app_name = PANPHON_TO_APP_FEATURE.get(panphon_name)
        if app_name is None:
            continue
        bundle[app_name] = panphon_value_to_app(value)
    return bundle


class PanPhonFeatureProvider:
    """Generate feature bundles from IPA symbols via PanPhon."""

    name: str = "PanPhon"

    def __init__(self) -> None:
        import panphon

        self._ft = panphon.FeatureTable()
        try:
            self.version: str = importlib.metadata.version("panphon")
        except importlib.metadata.PackageNotFoundError:
            self.version = "unknown"

    def display_label(self) -> str:
        # Bare name in the dropdown: the dialog's parent label
        # ("Features (delimited):") already makes the role clear,
        # and a parenthetical suffix on every provider would
        # clutter the row once more sources are added.
        return self.name

    def feature_names(self) -> tuple[str, ...]:
        """App-side feature names, in PanPhon's column order.

        Returned tuple is exactly the set of features
        :py:meth:`generate` will populate, so the dialog can
        pre-fill the features textarea with the same names the user
        will see in the grid.
        """
        return tuple(
            PANPHON_TO_APP_FEATURE[name]
            for name in self._ft.names
            if name in PANPHON_TO_APP_FEATURE
        )

    def generate(self, segments: list[str]) -> GeneratedInventory:
        """Resolve ``segments`` via PanPhon's
        :py:meth:`FeatureTable.word_fts`. Single-segment matches go
        into ``segments``; everything else (raise, zero matches,
        multiple matches, conversion failure) lands in
        ``unresolved`` with a human-readable warning. The caller
        seeds unresolved columns with
        :py:func:`phonology_shared.editor.providers.blank_bundle`.

        Features that no resolved segment specifies (every value is
        ``"0"`` across the resolved bundles) are dropped from both
        the returned ``features`` tuple and every per-segment
        bundle. This stops a small selection from pulling in every
        column the underlying source defines and producing a
        sparsely-populated inventory the user would then have to
        prune by hand. The full feature set is still surfaced when
        no segment resolves (so the user has columns to edit on the
        failure path) or when the input list is empty.
        """
        features = self.feature_names()
        resolved: dict[str, Mapping[str, str]] = {}
        unresolved: list[str] = []
        warnings: list[str] = []
        panphon_names = list(self._ft.names)

        for symbol in segments:
            try:
                parsed = self._ft.word_fts(symbol)
            except (KeyError, ValueError, RuntimeError, TypeError) as exc:
                # Narrow exception set so KeyboardInterrupt and
                # SystemExit propagate; PanPhon raises these four
                # types for unknown segments / malformed feature
                # tables, and any other class is a genuine bug
                # that should surface, not silently warn.
                unresolved.append(symbol)
                warnings.append(f"{symbol!r}: PanPhon lookup failed: {exc}")
                continue

            if len(parsed) == 0:
                unresolved.append(symbol)
                warnings.append(
                    f"{symbol!r}: PanPhon did not recognise this symbol; "
                    "edit the column by hand or remove it."
                )
                continue

            if len(parsed) > 1:
                unresolved.append(symbol)
                warnings.append(
                    f"{symbol!r}: PanPhon parsed this as "
                    f"{len(parsed)} segments; enter a single IPA "
                    "segment or edit manually."
                )
                continue

            try:
                resolved[symbol] = _segment_to_bundle(parsed[0], panphon_names)
            except (TypeError, ValueError) as exc:
                # The two raises in _segment_to_bundle: unexpected
                # Segment shape (TypeError) and value/name length
                # mismatch (ValueError). Anything else is a real bug
                # and should propagate instead of being swallowed as
                # a per-symbol unresolved warning.
                unresolved.append(symbol)
                warnings.append(
                    f"{symbol!r}: PanPhon feature conversion failed: " f"{exc}"
                )

        if resolved:
            features = prune_unused_features(features, resolved)
            resolved = restrict_bundles(resolved, features)

        return GeneratedInventory(
            features=features,
            segments=resolved,
            unresolved=tuple(unresolved),
            warnings=tuple(warnings),
        )
