"""Datetime parsing utilities for consistent datetime handling."""

from datetime import datetime
from typing import Any, Optional


def parse_datetime(value: Any) -> Optional[datetime]:
    """
    Parse datetime from various formats with flexible handling.

    This utility eliminates the repetitive pattern of:
        if value is None or isinstance(value, datetime):
            return value
        try:
            text = str(value).strip()
            if not text:
                return None
            text = text.replace('Z', '+00:00')
            return datetime.fromisoformat(text)
        except Exception:
            return None

    Usage:
        # Basic usage
        created_date = parse_datetime(jira_data.get('created'))

        # With optional chaining
        db_issue.created_date = parse_datetime(fields.get('created'))
        db_issue.updated_date = parse_datetime(fields.get('updated'))

    Args:
        value: Input value to parse (can be None, datetime, string, or any object)

    Returns:
        datetime object if parsing successful, None otherwise

    Examples:
        >>> parse_datetime(None)
        None

        >>> parse_datetime(datetime(2024, 1, 1))
        datetime.datetime(2024, 1, 1, 0, 0)

        >>> parse_datetime("2024-01-01T12:00:00Z")
        datetime.datetime(2024, 1, 1, 12, 0, tzinfo=datetime.timezone.utc)

        >>> parse_datetime("2024-01-01T12:00:00+00:00")
        datetime.datetime(2024, 1, 1, 12, 0, tzinfo=datetime.timezone.utc)

        >>> parse_datetime("")
        None

        >>> parse_datetime("invalid")
        None
    """
    if value is None or isinstance(value, datetime):
        return value

    try:
        text = str(value).strip()
        if not text:
            return None

        # Replace 'Z' timezone indicator with explicit UTC offset
        text = text.replace('Z', '+00:00')

        return datetime.fromisoformat(text)
    except Exception:
        return None
