# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Required Notice: Copyright 2026 John Winstead,
# https://github.com/jhnwnstd/phono-feature
"""Feature preset definitions for the inventory editor.

Re-exports :py:data:`FEATURE_PRESETS` from
:py:mod:`phonology_shared.editor.setup`, which is the
shared source consumed by both the desktop editor and the web
setup modal. Kept as a thin alias so existing
``from ...editor.presets import FEATURE_PRESETS`` imports stay
stable and the web bundle does not need to relay this submodule.
"""

from phonology_shared.editor.setup import FEATURE_PRESETS

__all__ = ["FEATURE_PRESETS"]
