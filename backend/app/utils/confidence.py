"""Confidence score utilities for traceability links."""

from __future__ import annotations

import math
from typing import Optional, TYPE_CHECKING

from sqlalchemy import case, or_
from sqlalchemy.sql.elements import ColumnElement

if TYPE_CHECKING:
    from sqlalchemy.orm.attributes import InstrumentedAttribute


def normalized_confidence_column(
    confidence_col: "InstrumentedAttribute",
) -> ColumnElement:
    """Create SQL expression that normalizes confidence for comparison.

    Legacy data may be stored as 0..100 (old scale). This expression
    normalizes it to 0..1 at query time for correct filtering.

    Args:
        confidence_col: The confidence column (e.g., ArtifactLink.confidence)

    Returns:
        SQLAlchemy expression that yields normalized confidence (0..1 scale)

    Example:
        stmt = stmt.where(normalized_confidence_column(ArtifactLink.confidence) >= 0.5)
    """
    return case(
        (confidence_col > 1.0, confidence_col / 100.0),
        else_=confidence_col,
    )


def confidence_filter(
    confidence_col: "InstrumentedAttribute",
    min_confidence: float,
) -> ColumnElement:
    """Create SQL filter for minimum confidence with legacy data support.

    Handles both new (0..1) and legacy (0..100) confidence values in database.
    NULL confidence values pass the filter (treated as "unknown, not low").

    Args:
        confidence_col: The confidence column (e.g., ArtifactLink.confidence)
        min_confidence: Minimum confidence threshold (0..1 scale)

    Returns:
        SQLAlchemy filter expression

    Example:
        stmt = stmt.where(confidence_filter(ArtifactLink.confidence, 0.5))
    """
    normalized = normalized_confidence_column(confidence_col)
    return or_(
        normalized >= min_confidence,
        confidence_col.is_(None),  # NULL passes through
    )


def normalize_confidence(value: Optional[float]) -> Optional[float]:
    """Normalize confidence to 0..1 scale.

    Handles legacy data that may be stored as 0..100.
    Values > 1.0 are assumed to be in the old 0..100 scale.
    NaN and Inf values are treated as invalid and return None.

    Args:
        value: Raw confidence value (may be 0..1 or legacy 0..100)

    Returns:
        Normalized confidence in 0..1 range, or None if invalid
    """
    if value is None:
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    if value > 1.0:
        # Legacy 0..100 scale - convert to 0..1
        return min(1.0, value / 100.0)
    return max(0.0, min(1.0, value))
