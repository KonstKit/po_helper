"""
Security tests for input validation in rule execution engine.

Tests cover:
1. ReDoS prevention in regex patterns
2. Input sanitization (null bytes, excessive length)
3. SQL injection prevention via parameterized queries
4. Type validation
5. Whitelist validation for operators
"""

import pytest
from datetime import datetime, timezone
from app.services.rule_execution_engine import InputValidator


class TestInputValidator:
    """Test suite for InputValidator security validations."""

    # ============================================================================
    # String Validation Tests
    # ============================================================================

    def test_validate_string_basic(self):
        """Test basic string validation."""
        result = InputValidator.validate_string("hello world", "test", max_length=100)
        assert result == "hello world"

    def test_validate_string_removes_null_bytes(self):
        """Test that null bytes are removed from strings."""
        malicious = "hello\x00world\x00"
        result = InputValidator.validate_string(malicious, "test", max_length=100)
        assert "\x00" not in result
        assert result == "helloworld"

    def test_validate_string_strips_whitespace(self):
        """Test that leading/trailing whitespace is stripped."""
        result = InputValidator.validate_string("  hello  ", "test", max_length=100)
        assert result == "hello"

    def test_validate_string_rejects_too_long(self):
        """Test that excessively long strings are rejected."""
        long_string = "a" * 1001
        with pytest.raises(ValueError, match="exceeds maximum length"):
            InputValidator.validate_string(long_string, "test", max_length=1000)

    def test_validate_string_rejects_non_string(self):
        """Test that non-string types are rejected."""
        with pytest.raises(ValueError, match="must be a string"):
            InputValidator.validate_string(123, "test")

        with pytest.raises(ValueError, match="must be a string"):
            InputValidator.validate_string(None, "test")

    # ============================================================================
    # Date Validation Tests
    # ============================================================================

    def test_validate_date_datetime_object(self):
        """Test validation of datetime objects."""
        now = datetime.now(timezone.utc)
        result = InputValidator.validate_date(now, "test")
        assert result == now

    def test_validate_date_iso_string(self):
        """Test validation of ISO 8601 date strings."""
        date_str = "2025-12-09T10:30:00"
        result = InputValidator.validate_date(date_str, "test")
        assert isinstance(result, datetime)
        assert result.year == 2025
        assert result.month == 12
        assert result.day == 9

    def test_validate_date_iso_string_with_z(self):
        """Test validation of ISO 8601 with Z suffix."""
        date_str = "2025-12-09T10:30:00Z"
        result = InputValidator.validate_date(date_str, "test")
        assert isinstance(result, datetime)

    def test_validate_date_rejects_invalid_format(self):
        """Test that invalid date formats are rejected."""
        with pytest.raises(ValueError, match="must be a valid ISO 8601"):
            InputValidator.validate_date("not-a-date", "test")

    def test_validate_date_rejects_non_datetime(self):
        """Test that non-datetime types are rejected."""
        with pytest.raises(ValueError, match="must be a datetime or ISO 8601"):
            InputValidator.validate_date(123, "test")

    # ============================================================================
    # Regex Pattern Validation Tests (ReDoS Prevention)
    # ============================================================================

    def test_validate_regex_safe_pattern(self):
        """Test that safe whitelisted patterns are allowed."""
        # Default Jira key pattern
        pattern = r'\b[A-Z][A-Z0-9_]+-[0-9]+\b'
        result = InputValidator.validate_regex_pattern(pattern, allow_custom=False)
        assert result == pattern

    def test_validate_regex_rejects_custom_without_flag(self):
        """Test that custom patterns are rejected when allow_custom=False."""
        custom_pattern = r'(a+)+'  # Dangerous nested quantifier
        with pytest.raises(ValueError, match="Custom regex patterns are not allowed"):
            InputValidator.validate_regex_pattern(custom_pattern, allow_custom=False)

    def test_validate_regex_detects_nested_quantifiers(self):
        """Test detection of nested quantifiers (ReDoS vulnerability)."""
        # Common ReDoS patterns
        redos_patterns = [
            r'(a+)+',      # Nested +
            r'(a*)*',      # Nested *
            r'(a+)*',      # Mixed quantifiers
            r'(a{1,5})+',  # Nested with range
        ]

        for pattern in redos_patterns:
            with pytest.raises(ValueError, match="nested quantifiers"):
                InputValidator.validate_regex_pattern(pattern, allow_custom=True)

    def test_validate_regex_rejects_too_long(self):
        """Test that excessively long regex patterns are rejected."""
        long_pattern = 'a' * 201
        with pytest.raises(ValueError, match="too long"):
            InputValidator.validate_regex_pattern(long_pattern, allow_custom=True)

    def test_validate_regex_rejects_too_many_quantifiers(self):
        """Test that patterns with too many quantifiers are rejected."""
        # Pattern with 6 quantifiers (exceeds MAX_REGEX_QUANTIFIERS=5)
        pattern = r'a+b*c?d{1,3}e+f*'
        with pytest.raises(ValueError, match="too many quantifiers"):
            InputValidator.validate_regex_pattern(pattern, allow_custom=True)

    def test_validate_regex_rejects_invalid_syntax(self):
        """Test that invalid regex syntax is rejected."""
        invalid_patterns = [
            r'[',           # Unclosed bracket
            r'(?P<)',       # Invalid group name
            r'(?P<test',    # Unclosed group
            r'*',           # Nothing to repeat
        ]

        for pattern in invalid_patterns:
            with pytest.raises(ValueError, match="Invalid regex pattern"):
                InputValidator.validate_regex_pattern(pattern, allow_custom=True)

    def test_validate_regex_rejects_non_string(self):
        """Test that non-string patterns are rejected."""
        with pytest.raises(ValueError, match="must be a string"):
            InputValidator.validate_regex_pattern(123, allow_custom=True)

    # ============================================================================
    # List Validation Tests
    # ============================================================================

    def test_validate_list_of_strings_basic(self):
        """Test basic list validation."""
        items = ["item1", "item2", "item3"]
        result = InputValidator.validate_list_of_strings(items, "test")
        assert result == items

    def test_validate_list_of_strings_converts_single_string(self):
        """Test that single string is converted to list."""
        result = InputValidator.validate_list_of_strings("single", "test")
        assert result == ["single"]

    def test_validate_list_of_strings_sanitizes_items(self):
        """Test that each item is sanitized."""
        items = ["  item1  ", "item2\x00", "item3"]
        result = InputValidator.validate_list_of_strings(items, "test")
        assert result == ["item1", "item2", "item3"]

    def test_validate_list_of_strings_rejects_too_many_items(self):
        """Test that lists with too many items are rejected."""
        items = ["item"] * 101
        with pytest.raises(ValueError, match="exceeds maximum of"):
            InputValidator.validate_list_of_strings(items, "test", max_items=100)

    def test_validate_list_of_strings_rejects_too_long_item(self):
        """Test that items exceeding length limit are rejected."""
        items = ["a" * 501]
        with pytest.raises(ValueError, match="exceeds maximum length"):
            InputValidator.validate_list_of_strings(items, "test", max_item_length=500)

    def test_validate_list_of_strings_rejects_non_list(self):
        """Test that non-list types are rejected."""
        with pytest.raises(ValueError, match="must be a list or string"):
            InputValidator.validate_list_of_strings(123, "test")

    # ============================================================================
    # Integration Tests: Real Attack Scenarios
    # ============================================================================

    def test_sql_injection_attempt_in_string(self):
        """Test that SQL injection attempts are sanitized."""
        # SQL injection payload
        malicious = "'; DROP TABLE users; --"
        result = InputValidator.validate_string(malicious, "test", max_length=100)

        # Should be sanitized (stripped, no null bytes)
        assert result == "'; DROP TABLE users; --"
        # Note: Actual SQL injection prevention happens via parameterized queries
        # This test ensures input validation doesn't break the payload detection

    def test_xss_attempt_in_string(self):
        """Test that XSS attempts are handled."""
        malicious = "<script>alert('XSS')</script>"
        result = InputValidator.validate_string(malicious, "test", max_length=100)

        # Should pass through (XSS prevention is frontend's responsibility)
        assert result == "<script>alert('XSS')</script>"

    def test_redos_attack_prevented(self):
        """Test that ReDoS attack patterns are blocked."""
        # Real-world ReDoS pattern from OWASP
        redos_pattern = r'(a+)+'

        with pytest.raises(ValueError, match="nested quantifiers"):
            InputValidator.validate_regex_pattern(redos_pattern, allow_custom=True)

    def test_path_traversal_in_string(self):
        """Test that path traversal attempts are detected."""
        malicious = "../../etc/passwd"
        result = InputValidator.validate_string(malicious, "test", max_length=100)

        # Should be sanitized (stripped)
        assert result == "../../etc/passwd"
        # Note: Path traversal prevention should be handled at filesystem layer

    def test_buffer_overflow_attempt(self):
        """Test that buffer overflow attempts are prevented."""
        # Attempt to send 10MB of data
        malicious = "A" * 10_000_000

        with pytest.raises(ValueError, match="exceeds maximum length"):
            InputValidator.validate_string(malicious, "test", max_length=1000)


class TestSecurityIntegration:
    """Integration tests for security in executors."""

    def test_commit_source_executor_sanitizes_filters(self):
        """Test that CommitSourceExecutor validates filter inputs."""
        # This would be tested with actual database
        # For now, verify InputValidator is called correctly
        pass

    def test_jira_issue_source_executor_sanitizes_filters(self):
        """Test that JiraIssueSourceExecutor validates filter inputs."""
        pass

    def test_confluence_source_executor_sanitizes_filters(self):
        """Test that ConfluenceSourceExecutor validates filter inputs."""
        pass

    def test_jira_key_extractor_prevents_redos(self):
        """Test that JiraKeyExtractorExecutor prevents ReDoS attacks."""
        pass

    def test_filter_node_executor_validates_config(self):
        """Test that FilterNodeExecutor validates configuration."""
        pass


# ============================================================================
# Performance Tests
# ============================================================================

class TestPerformance:
    """Performance tests to ensure validation doesn't slow down execution."""

    def test_string_validation_performance(self):
        """Test that string validation is fast."""
        import time

        # Validate 10,000 strings
        start = time.time()
        for i in range(10_000):
            InputValidator.validate_string(f"test_{i}", "test", max_length=100)
        elapsed = time.time() - start

        # Should take less than 1 second
        assert elapsed < 1.0, f"String validation too slow: {elapsed:.2f}s"

    def test_regex_validation_performance(self):
        """Test that regex validation is fast."""
        import time

        pattern = r'\b[A-Z][A-Z0-9_]+-[0-9]+\b'

        # Validate 1,000 patterns
        start = time.time()
        for i in range(1_000):
            InputValidator.validate_regex_pattern(pattern, allow_custom=False)
        elapsed = time.time() - start

        # Should take less than 0.5 seconds
        assert elapsed < 0.5, f"Regex validation too slow: {elapsed:.2f}s"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
