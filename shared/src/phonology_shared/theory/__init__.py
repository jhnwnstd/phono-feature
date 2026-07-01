"""Phonological analysis engine.

Reads :py:mod:`phonology_shared.data` inventories and answers analytical
queries: natural classes, contrastive features, feature categories,
feature-geometry inference. No display knowledge.
"""

from __future__ import annotations

from phonology_shared.theory.feature_engine import FeatureEngine

__all__ = ["FeatureEngine"]
