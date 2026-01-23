from __future__ import annotations

import re
from datetime import datetime
from typing import Any, List


class InputValidator:
    """Security validator for user inputs to prevent injection attacks."""

    SAFE_REGEX_PATTERNS = {
        "jira_key": r"\b[A-Z][A-Z0-9_]+-[0-9]+\b",
        "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        "url": r"https?://[^\s]+",
        "alphanumeric": r"[A-Za-z0-9]+",
        "word": r"\w+",
    }

    MAX_REGEX_LENGTH = 200
    MAX_REGEX_GROUPS = 10
    MAX_REGEX_QUANTIFIERS = 5

    @staticmethod
    def validate_string(value: Any, field_name: str, max_length: int = 1000) -> str:
        """Validate and sanitize string input."""
        if not isinstance(value, str):
            raise ValueError(f"{field_name} must be a string, got {type(value).__name__}")

        if len(value) > max_length:
            raise ValueError(f"{field_name} exceeds maximum length of {max_length}")

        sanitized = value.replace("\x00", "").strip()
        return sanitized

    @staticmethod
    def validate_date(value: Any, field_name: str) -> datetime:
        """Validate date input."""
        if isinstance(value, datetime):
            return value

        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError(f"{field_name} must be a valid ISO 8601 date string")

        raise ValueError(f"{field_name} must be a datetime or ISO 8601 string")

    @staticmethod
    def validate_regex_pattern(pattern: str, allow_custom: bool = False) -> str:
        """Validate regex pattern to prevent ReDoS attacks."""
        if not isinstance(pattern, str):
            raise ValueError(f"Pattern must be a string, got {type(pattern).__name__}")

        if not allow_custom:
            if pattern not in InputValidator.SAFE_REGEX_PATTERNS.values():
                is_safe = False
                for safe_pattern in InputValidator.SAFE_REGEX_PATTERNS.values():
                    if pattern == safe_pattern:
                        is_safe = True
                        break

                if not is_safe:
                    raise ValueError(
                        "Custom regex patterns are not allowed. Use one of: "
                        f"{', '.join(InputValidator.SAFE_REGEX_PATTERNS.keys())}"
                    )

        if len(pattern) > InputValidator.MAX_REGEX_LENGTH:
            raise ValueError(
                f"Regex pattern too long (max {InputValidator.MAX_REGEX_LENGTH} chars)"
            )

        if re.search(r"\([^)]*[+*?{][^)]*\)[+*?{]", pattern):
            raise ValueError("Regex pattern contains nested quantifiers (potential ReDoS)")

        quantifier_count = len(re.findall(r"[+*?{]", pattern))
        if quantifier_count > InputValidator.MAX_REGEX_QUANTIFIERS:
            raise ValueError(
                f"Regex pattern has too many quantifiers (max {InputValidator.MAX_REGEX_QUANTIFIERS})"
            )

        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"Invalid regex pattern: {str(exc)}")

        return pattern

    @staticmethod
    def validate_list_of_strings(
        value: Any,
        field_name: str,
        max_items: int = 100,
        max_item_length: int = 500,
    ) -> List[str]:
        """Validate list of strings."""
        if isinstance(value, str):
            value = [value]

        if not isinstance(value, list):
            raise ValueError(f"{field_name} must be a list or string")

        if len(value) > max_items:
            raise ValueError(f"{field_name} exceeds maximum of {max_items} items")

        validated = []
        for item in value:
            validated.append(
                InputValidator.validate_string(item, f"{field_name} item", max_item_length)
            )

        return validated
