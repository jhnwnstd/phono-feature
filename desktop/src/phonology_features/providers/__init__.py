"""Desktop-side :py:class:`FeatureProvider` registry.

Holds desktop-only implementations of the
:py:mod:`phonology_shared.editor.providers` Protocol. Each provider
ships with a lazy import so a desktop install without the optional
dependency stays usable; the registry probes module availability
with :py:func:`importlib.util.find_spec` rather than swallowing
``ImportError`` at construction.

Provider instances are cached at module scope. The PanPhon
``FeatureTable`` reads ``ipa_all.csv`` into a pandas DataFrame and
walks ~32k rows during construction (~2 s on a typical desktop);
re-constructing for every InputDialog open turned every "New"
click in the Editor into a multi-second stall. The cache pays the
cost once on first use and serves every subsequent dialog open in
microseconds.

Web client-side providers (when they exist) live under ``web/`` and
implement the same shared Protocol; the dialog code is agnostic to
which side instantiated the provider as long as it implements
``name``, ``version``, ``feature_names``, ``display_label``, and
``generate``.
"""

from __future__ import annotations

import functools
import importlib.util
import threading

from phonology_shared.editor.providers import FeatureProvider


@functools.lru_cache(maxsize=1)
def _panphon_instance() -> FeatureProvider | None:
    """Lazily construct (and cache) the PanPhon provider.

    First call pays the ~2 s panphon-data-load cost; subsequent
    calls return the same instance in O(1). Returns ``None`` when
    the optional ``panphon`` package is not installed, so a desktop
    install without the extra stays fully functional.

    The provider holds no per-inventory state, so sharing one
    instance across every dialog open is safe; ``generate(...)``
    is read-only against ``self._ft``.
    """
    if importlib.util.find_spec("panphon") is None:
        return None
    from phonology_features.providers.panphon_provider import (
        PanPhonFeatureProvider,
    )

    return PanPhonFeatureProvider()


def available_providers() -> list[FeatureProvider]:
    """Return every :py:class:`FeatureProvider` whose backing
    dependency is installed.

    Order is stable across calls. After the first call the
    underlying instance is cached, so subsequent calls cost
    nothing measurable.
    """
    inst = _panphon_instance()
    return [inst] if inst is not None else []


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


def prewarm_in_background() -> None:
    """Kick off a daemon thread that constructs the cached provider.

    Without this call the first ``available_providers()`` invocation
    (typically from the first Editor ``New`` click) blocks the UI
    thread for ~2 s while ``panphon.FeatureTable()`` walks
    ``ipa_all.csv`` into a pandas DataFrame. Running that
    construction off the UI thread at app startup means the cache
    is warm by the time the user gets to the dialog; the first
    click then completes in microseconds like every subsequent one.

    Thread-safe by virtue of :py:func:`functools.lru_cache`'s
    internal lock: if the user clicks New before the background
    thread completes, the UI thread blocks on the same lock and
    receives the eventual result (no duplicate construction). If
    the user never opens the Editor, the daemon thread quietly
    finishes its work and exits with the process.

    Idempotent: subsequent calls return immediately because the
    cache is already populated.
    """
    if _panphon_instance.cache_info().currsize > 0:
        return
    threading.Thread(
        target=_panphon_instance,
        name="panphon-prewarm",
        daemon=True,
    ).start()
