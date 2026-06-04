"""Feature preset definitions for the inventory builder.

Re-exports :py:data:`FEATURE_PRESETS` from
:py:mod:`phonology_shared.editor.setup`, which is the
shared source consumed by both the desktop builder and the web
setup modal. Kept as a thin alias so existing
``from ...builder.presets import FEATURE_PRESETS`` imports stay
stable and the web bundle does not need to relay this submodule.
"""

from phonology_shared.editor.setup import FEATURE_PRESETS

__all__ = ["FEATURE_PRESETS"]
