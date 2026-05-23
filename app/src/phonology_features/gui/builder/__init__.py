"""
gui/builder; Inventory Builder package.

Re-exports InventoryBuilder so existing imports continue to work:
    from phonology_features.gui.builder import InventoryBuilder
"""

from phonology_features.gui.builder.window import InventoryBuilder

__all__ = ["InventoryBuilder"]
