"""
Confidence Scoring Service for Traceability Links.

Calculates confidence scores for artifact links based on multiple factors:
- text_similarity: Semantic/textual similarity between artifacts
- temporal_proximity: How close in time the artifacts were created/updated
- author_match: Whether the same person is involved in both artifacts
- explicit_reference: Direct ID/key mentions in text
- path_similarity: File path patterns (for commits/code)
- link_type_weight: Different link types have different base confidences
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field


@dataclass
class ConfidenceFactors:
    """Individual confidence factors with their weights."""

    text_similarity: float = 0.0
    temporal_proximity: float = 0.0
    author_match: float = 0.0
    explicit_reference: float = 0.0
    path_similarity: float = 0.0
    context_match: float = 0.0

    # Weights for each factor (must sum to 1.0)
    weights: Dict[str, float] = field(
        default_factory=lambda: {
            "text_similarity": 0.25,
            "temporal_proximity": 0.15,
            "author_match": 0.15,
            "explicit_reference": 0.30,
            "path_similarity": 0.10,
            "context_match": 0.05,
        }
    )

    def calculate_total(self) -> float:
        """Calculate weighted total confidence score."""
        total = (
            self.text_similarity * self.weights["text_similarity"]
            + self.temporal_proximity * self.weights["temporal_proximity"]
            + self.author_match * self.weights["author_match"]
            + self.explicit_reference * self.weights["explicit_reference"]
            + self.path_similarity * self.weights["path_similarity"]
            + self.context_match * self.weights["context_match"]
        )
        return min(max(total, 0.0), 1.0)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "text_similarity": self.text_similarity,
            "temporal_proximity": self.temporal_proximity,
            "author_match": self.author_match,
            "explicit_reference": self.explicit_reference,
            "path_similarity": self.path_similarity,
            "context_match": self.context_match,
            "weights": self.weights,
            "total": self.calculate_total(),
        }


class ConfidenceScoringService:
    """Service for calculating confidence scores between artifacts."""

    # Jira key pattern
    JIRA_KEY_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")

    # Common requirement keywords
    REQUIREMENT_KEYWORDS = {
        "requirement",
        "acceptance",
        "criteria",
        "shall",
        "must",
        "should",
        "need",
        "feature",
        "user story",
        "epic",
    }

    # Test-related keywords
    TEST_KEYWORDS = {
        "test",
        "verify",
        "validate",
        "check",
        "assert",
        "expect",
        "scenario",
        "given",
        "when",
        "then",
    }

    def calculate_confidence(
        self,
        from_artifact: Dict[str, Any],
        to_artifact: Dict[str, Any],
        link_type: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Calculate confidence score between two artifacts.

        Args:
            from_artifact: Source artifact data
            to_artifact: Target artifact data
            link_type: Type of link (implements, tests, etc.)
            context: Additional context (extracted text, etc.)

        Returns:
            Tuple of (confidence_score, factors_dict)
        """
        factors = ConfidenceFactors()

        # Calculate each factor
        factors.text_similarity = self._calculate_text_similarity(from_artifact, to_artifact)
        factors.temporal_proximity = self._calculate_temporal_proximity(from_artifact, to_artifact)
        factors.author_match = self._calculate_author_match(from_artifact, to_artifact)
        factors.explicit_reference = self._calculate_explicit_reference(
            from_artifact, to_artifact, context
        )
        factors.path_similarity = self._calculate_path_similarity(from_artifact, to_artifact)
        factors.context_match = self._calculate_context_match(from_artifact, to_artifact, link_type)

        # Apply link type modifier
        base_confidence = factors.calculate_total()
        link_modifier = self._get_link_type_modifier(link_type)
        final_confidence = min(base_confidence * link_modifier, 1.0)

        factors_dict = factors.to_dict()
        factors_dict["link_type_modifier"] = link_modifier
        factors_dict["final_score"] = final_confidence

        return final_confidence, factors_dict

    def _calculate_text_similarity(
        self,
        from_artifact: Dict[str, Any],
        to_artifact: Dict[str, Any],
    ) -> float:
        """
        Calculate text similarity using simple TF-IDF-like approach.

        For full TF-IDF, we'd need scikit-learn, but this is a simplified version.
        """
        from_text = self._get_artifact_text(from_artifact)
        to_text = self._get_artifact_text(to_artifact)

        if not from_text or not to_text:
            return 0.0

        # Tokenize and normalize
        from_words = set(self._tokenize(from_text))
        to_words = set(self._tokenize(to_text))

        if not from_words or not to_words:
            return 0.0

        # Jaccard similarity
        intersection = len(from_words & to_words)
        union = len(from_words | to_words)

        return intersection / union if union > 0 else 0.0

    def _calculate_temporal_proximity(
        self,
        from_artifact: Dict[str, Any],
        to_artifact: Dict[str, Any],
    ) -> float:
        """Calculate score based on time proximity (closer = higher score)."""
        from_time = self._get_timestamp(from_artifact)
        to_time = self._get_timestamp(to_artifact)

        if from_time is None or to_time is None:
            return 0.5  # Neutral if no timestamps

        # Calculate time difference in days
        diff = abs((from_time - to_time).total_seconds() / 86400)

        # Score decreases with time difference
        # Full score if same day, half score at 7 days, near zero at 30+ days
        if diff < 1:
            return 1.0
        elif diff < 7:
            return 0.8 - (diff / 7) * 0.3
        elif diff < 30:
            return 0.5 - (diff / 30) * 0.3
        else:
            return max(0.1, 0.2 - (diff / 365) * 0.1)

    def _calculate_author_match(
        self,
        from_artifact: Dict[str, Any],
        to_artifact: Dict[str, Any],
    ) -> float:
        """Calculate score based on author/assignee match."""
        from_author = self._get_author(from_artifact)
        to_author = self._get_author(to_artifact)

        if not from_author or not to_author:
            return 0.0

        # Normalize emails/names
        from_author = from_author.lower().strip()
        to_author = to_author.lower().strip()

        if from_author == to_author:
            return 1.0

        # Partial match (same email domain or similar name)
        if "@" in from_author and "@" in to_author:
            from_domain = from_author.split("@")[-1]
            to_domain = to_author.split("@")[-1]
            if from_domain == to_domain:
                return 0.3

        return 0.0

    def _calculate_explicit_reference(
        self,
        from_artifact: Dict[str, Any],
        to_artifact: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> float:
        """Calculate score based on explicit ID/key references."""
        to_key = to_artifact.get("external_id") or to_artifact.get("display_key")
        if not to_key:
            return 0.0

        # Check in from_artifact's text fields
        from_text = self._get_artifact_text(from_artifact)

        # Also check context if provided
        if context:
            from_text += " " + str(context.get("extracted_text", ""))

        if not from_text:
            return 0.0

        # Direct key match
        if to_key.upper() in from_text.upper():
            return 1.0

        # Check for Jira key pattern
        found_keys = self.JIRA_KEY_PATTERN.findall(from_text.upper())
        if to_key.upper() in found_keys:
            return 1.0

        # Partial match (e.g., just the number part)
        if "-" in to_key:
            key_parts = to_key.split("-")
            if len(key_parts) == 2 and key_parts[1] in from_text:
                return 0.5

        return 0.0

    def _calculate_path_similarity(
        self,
        from_artifact: Dict[str, Any],
        to_artifact: Dict[str, Any],
    ) -> float:
        """Calculate similarity based on file paths (for code artifacts)."""
        from_meta = from_artifact.get("meta") or {}
        to_meta = to_artifact.get("meta") or {}

        from_paths = from_meta.get("files_changed", []) or from_meta.get("file_path", "")
        to_paths = to_meta.get("files_changed", []) or to_meta.get("file_path", "")

        if not from_paths or not to_paths:
            return 0.0

        # Normalize to lists
        if isinstance(from_paths, str):
            from_paths = [from_paths]
        if isinstance(to_paths, str):
            to_paths = [to_paths]

        # Calculate path overlap
        from_dirs = set()
        to_dirs = set()

        for path in from_paths:
            parts = path.split("/")
            for i in range(1, len(parts)):
                from_dirs.add("/".join(parts[:i]))

        for path in to_paths:
            parts = path.split("/")
            for i in range(1, len(parts)):
                to_dirs.add("/".join(parts[:i]))

        if not from_dirs or not to_dirs:
            return 0.0

        # Jaccard similarity of directory paths
        intersection = len(from_dirs & to_dirs)
        union = len(from_dirs | to_dirs)

        return intersection / union if union > 0 else 0.0

    def _calculate_context_match(
        self,
        from_artifact: Dict[str, Any],
        to_artifact: Dict[str, Any],
        link_type: str,
    ) -> float:
        """Calculate score based on contextual relevance."""
        from_type = from_artifact.get("type", "")
        to_type = to_artifact.get("type", "")
        from_text = self._get_artifact_text(from_artifact).lower()
        to_text = self._get_artifact_text(to_artifact).lower()

        score = 0.0

        # Check for expected patterns based on link type
        if link_type == "implements":
            # Requirement -> Task should have requirement keywords
            if from_type == "requirement" or from_type == "confluence_page":
                if any(kw in from_text for kw in self.REQUIREMENT_KEYWORDS):
                    score += 0.5
            if to_type in ("jira_issue", "commit", "pr"):
                score += 0.3

        elif link_type == "tests":
            # Test case -> Requirement
            if any(kw in from_text or kw in to_text for kw in self.TEST_KEYWORDS):
                score += 0.5
            if from_type == "test_case" or to_type == "test_case":
                score += 0.3

        elif link_type == "relates_to":
            # General relation - lower base score
            score = 0.3

        return min(score, 1.0)

    def _get_link_type_modifier(self, link_type: str) -> float:
        """Get confidence modifier based on link type."""
        modifiers = {
            "implements": 1.0,  # High confidence expected
            "tests": 1.0,  # High confidence expected
            "deploys": 0.95,  # Slightly lower (automated)
            "derives_from": 0.9,  # Derived relationships
            "relates_to": 0.7,  # Generic relationship (lower confidence)
            "blocks": 0.85,  # Blocking relationships
        }
        return modifiers.get(link_type, 0.8)

    def _get_artifact_text(self, artifact: Dict[str, Any]) -> str:
        """Extract searchable text from artifact."""
        parts = []

        if artifact.get("title"):
            parts.append(str(artifact["title"]))
        if artifact.get("display_key"):
            parts.append(str(artifact["display_key"]))
        if artifact.get("external_id"):
            parts.append(str(artifact["external_id"]))

        # Check meta for additional text
        meta = artifact.get("meta") or {}
        if meta.get("description"):
            parts.append(str(meta["description"]))
        if meta.get("summary"):
            parts.append(str(meta["summary"]))
        if meta.get("commit_message"):
            parts.append(str(meta["commit_message"]))

        return " ".join(parts)

    def _get_timestamp(self, artifact: Dict[str, Any]) -> Optional[datetime]:
        """Extract timestamp from artifact."""
        for field_name in ["created_at", "updated_at", "started_at", "committed_at"]:
            value = artifact.get(field_name)
            if value:
                if isinstance(value, datetime):
                    return value
                try:
                    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass

        # Check meta
        meta = artifact.get("meta") or {}
        for field_name in ["created", "updated", "date"]:
            value = meta.get(field_name)
            if value:
                try:
                    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass

        return None

    def _get_author(self, artifact: Dict[str, Any]) -> Optional[str]:
        """Extract author/assignee from artifact."""
        # Direct fields
        for field_name in ["author", "assignee", "assignee_email", "author_email", "created_by"]:
            value = artifact.get(field_name)
            if value:
                return str(value)

        # Check meta
        meta = artifact.get("meta") or {}
        for field_name in ["author", "assignee", "assignee_email", "author_email", "creator"]:
            value = meta.get(field_name)
            if value:
                return str(value)

        return None

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text into words."""
        # Simple tokenization: lowercase, split on non-alphanumeric
        text = text.lower()
        words = re.split(r"[^a-z0-9]+", text)

        # Filter out short words and stopwords
        stopwords = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
            "from",
            "as",
            "is",
            "was",
            "are",
            "were",
            "be",
            "been",
            "being",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "must",
            "this",
            "that",
            "these",
            "those",
            "it",
        }

        return [w for w in words if len(w) > 2 and w not in stopwords]


# Singleton instance
confidence_scoring_service = ConfidenceScoringService()
