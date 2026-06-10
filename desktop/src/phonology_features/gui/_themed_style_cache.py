"""Shared themed-style cache for widgets that rebuild their QSS
strings on palette changes.

Both :py:class:`SegmentButton` and :py:class:`FeatureRow` (and any
future themed widget) cache their per-state stylesheet strings at
class level so a 140-segment palette swap doesn't redo the
f-string interpolation 140 times. The cache must invalidate when
:py:mod:`palette` swaps either the light/dark theme axis or the
standard/colorblind mode axis; keying on the monotonic
``palette.theme_version`` integer captures both.

This module centralises the cache pattern so a future themed
widget can't forget to key on ``theme_version`` and end up with
stale colours after a palette toggle. Use as a class-method
helper bound to a ``_styles_cache`` ClassVar on the host class.
"""

from __future__ import annotations

from typing import Callable, TypeVar

import phonology_shared.presentation.palette as _palette

K = TypeVar("K")


def styles_for_active_theme(
    cache: dict[int, dict[K, str]],
    builder: Callable[[], dict[K, str]],
) -> dict[K, str]:
    """Return ``builder()`` keyed on the active palette version.

    Cache hit: the dict from the last call at the same
    ``palette.theme_version`` (object identity preserved so
    consumers can skip work via ``is`` comparison). Cache miss:
    invoke ``builder()`` once and store the result for the current
    version. The cache grows by one entry per distinct version
    seen during the process lifetime, which is bounded by the
    number of unique (theme, mode) combinations the user toggles
    through (currently 4) plus the warmup pass, so single-digit
    entries in practice.

    The function takes the cache dict by reference so the caller
    owns its lifetime; the host class can clear it (e.g. in
    tests) without going through this module.
    """
    version = _palette.theme_version
    cached = cache.get(version)
    if cached is None:
        cached = builder()
        cache[version] = cached
    return cached
