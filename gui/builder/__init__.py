"""
gui/builder; Inventory Builder package.

Re-exports InventoryBuilder so existing imports continue to work:
    from gui.builder import InventoryBuilder
"""

from gui.builder.window import InventoryBuilder

__all__ = ["InventoryBuilder"]
