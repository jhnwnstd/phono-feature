"""Back-compat shim. The validator is now ``Inventory.parse``.

This module exists so external consumers that import
``validate_inventory_data`` keep working. New code should call
``Inventory.parse(raw)`` directly and catch ``ValidationError`` --
that's the single source of truth for "is this inventory valid".

Behavioural change vs. the previous standalone validator:
  - All formerly-warning conditions (missing 'features', undeclared
    segment features, style nits like lowercase / all-caps names)
    are NOT reported. The new contract is strict: anything that would
    have desynchronized the validator and the engine is an error.
  - The empty-feature-name ``IndexError`` crash is gone -- ``parse``
    catches the empty string and reports it as a structured issue.
"""

from __future__ import annotations

from phonology_features.engine.inventory import Inventory, ValidationError


def validate_inventory_data(data: object) -> tuple[list[str], list[str]]:
    """Return ``(errors, warnings)``. Warnings is always empty.

    Kept for GUI surfaces that expect the two-tuple shape; prefer
    catching ``ValidationError`` from ``Inventory.parse`` in new code.
    """
    try:
        Inventory.parse(data)
    except ValidationError as e:
        return list(e.issues), []
    return [], []
