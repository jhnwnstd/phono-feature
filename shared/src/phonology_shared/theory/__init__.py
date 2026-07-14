# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Required Notice: Copyright 2026 John Winstead,
# https://github.com/jhnwnstd/phono-feature
"""Phonological analysis engine.

Reads :py:mod:`phonology_shared.data` inventories and answers analytical
queries: natural classes, contrastive features, feature categories,
feature-geometry inference. No display knowledge.
"""

from __future__ import annotations

from phonology_shared.theory.feature_engine import FeatureEngine

__all__ = ["FeatureEngine"]
