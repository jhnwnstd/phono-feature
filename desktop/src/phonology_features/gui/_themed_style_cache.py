"""Shared themed-style cache for widgets that rebuild their QSS
strings on palette changes.

Both :py:class:`SegmentButton` and :py:class:`FeatureRow` (and any
future themed widget) cache their per-state stylesheet strings at
class level so a 140-segment palette swap doesn't redo the
f-string interpolation 140 times. The cache keys on the STABLE
palette identity ``(theme, mode)`` rather than the monotonic
``palette.theme_version`` counter: the counter increments on every
toggle, so returning to a previously-seen combination was always a
miss, every light/dark round trip rebuilt all style strings, and
the dict gained one entry per toggle for the process lifetime.
Identity keying makes toggle-backs true hits and bounds the cache
at the four real (theme, mode) combinations.

This module centralises the cache pattern so a future themed
widget can't forget the invalidation rule and end up with stale
colours after a palette toggle. Use as a class-method helper
bound to a ``_styles_cache`` ClassVar on the host class.
"""

from __future__ import annotations

from typing import Callable, TypeVar

import phonology_shared.presentation.palette as _palette

K = TypeVar("K")


def styles_for_active_theme(
    cache: dict[tuple[str, str], dict[K, str]],
    builder: Callable[[], dict[K, str]],
) -> dict[K, str]:
    """Return ``builder()`` keyed on the active (theme, mode) pair.

    Cache hit: the dict from the last call at the same palette
    identity (object identity preserved so consumers can skip work
    via ``is`` comparison). Cache miss: invoke ``builder()`` once
    and store the result for the current identity.

    The function takes the cache dict by reference so the caller
    owns its lifetime; the host class can clear it (e.g. in
    tests) without going through this module.
    """
    key = (_palette.get_theme_name(), _palette.get_palette_mode())
    cached = cache.get(key)
    if cached is None:
        cached = builder()
        cache[key] = cached
    return cached
