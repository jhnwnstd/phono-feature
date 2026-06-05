"""Desktop-side :py:class:`FeatureProvider` registry.

Holds desktop-only implementations of the
:py:mod:`phonology_shared.editor.providers` Protocol. Each provider
ships with a lazy import so a desktop install without the optional
dependency stays usable; the registry probes module availability
with :py:func:`importlib.util.find_spec` rather than swallowing
``ImportError`` at construction.

Web client-side providers (when they exist) live under ``web/`` and
implement the same shared Protocol; the dialog code is agnostic to
which side instantiated the provider as long as it implements
``name``, ``version``, ``feature_names``, ``display_label``, and
``generate``.
"""

from __future__ import annotations

import importlib.util

from phonology_shared.editor.providers import FeatureProvider


def available_providers() -> list[FeatureProvider]:
    """Return every :py:class:`FeatureProvider` whose backing
    dependency is installed.

    Probed without importing the heavy modules, so calling this from
    UI-construction code is cheap. Order is stable across calls.
    """
    providers: list[FeatureProvider] = []
    if importlib.util.find_spec("panphon") is not None:
        from phonology_features.providers.panphon_provider import (
            PanPhonFeatureProvider,
        )

        providers.append(PanPhonFeatureProvider())
    return providers


def provider_by_name(name: str) -> FeatureProvider | None:
    """Look up a provider by its :py:attr:`FeatureProvider.name`.

    Returns ``None`` for unknown names so callers can treat
    "PanPhon picked when panphon is uninstalled" as a graceful
    fall-through to the blank-grid path.
    """
    for provider in available_providers():
        if provider.name == name:
            return provider
    return None
