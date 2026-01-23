"""
Text similarity service for auto-linking artifacts using TF-IDF.

This service computes text similarity between artifacts to suggest potential links
based on content similarity.
"""

from __future__ import annotations

import re
import logging
from typing import Any, List, Dict, Tuple, Optional
from dataclasses import dataclass

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.traceability import Artifact, ArtifactLink, SuggestedLink

logger = logging.getLogger(__name__)


@dataclass
class SimilarityResult:
    """Represents a similarity match between two artifacts."""

    from_artifact_id: int
    to_artifact_id: int
    similarity_score: float
    suggested_link_type: str
    reason: str
    method: str = "tfidf"


class TextSimilarityService:
    """
    Service for computing text similarity between artifacts using TF-IDF.

    Uses TF-IDF vectors and cosine similarity to find semantically similar
    artifacts that may have traceability relationships.
    """

    # Artifact type pairs that commonly have links
    LINKABLE_TYPE_PAIRS: List[Tuple[str, str, str]] = [
        ("requirement", "jira_issue", "implements"),
        ("requirement", "test_case", "tests"),
        ("jira_issue", "commit", "implements"),
        ("jira_issue", "pr", "implements"),
        ("jira_issue", "test_case", "tests"),
        ("confluence_page", "jira_issue", "relates_to"),
        ("confluence_page", "requirement", "derives_from"),
        ("test_case", "jira_issue", "tests"),
    ]

    # Stop words specific to software development context
    DEV_STOP_WORDS = [
        "bug",
        "fix",
        "feature",
        "task",
        "story",
        "epic",
        "sprint",
        "jira",
        "ticket",
        "issue",
        "pr",
        "pull",
        "request",
        "merge",
        "commit",
        "branch",
        "master",
        "main",
        "develop",
        "release",
        "todo",
        "wip",
        "done",
        "review",
        "approved",
        "closed",
        "open",
        "update",
        "add",
        "remove",
        "delete",
        "create",
        "new",
        "old",
    ]

    def __init__(
        self,
        min_similarity: float = 0.3,
        max_suggestions_per_artifact: int = 5,
        ngram_range: Tuple[int, int] = (1, 2),
    ):
        """
        Initialize the text similarity service.

        Args:
            min_similarity: Minimum cosine similarity threshold for suggestions
            max_suggestions_per_artifact: Maximum suggestions to generate per artifact
            ngram_range: Range of n-grams to use in TF-IDF
        """
        self.min_similarity = min_similarity
        self.max_suggestions_per_artifact = max_suggestions_per_artifact

        self.vectorizer = TfidfVectorizer(
            max_features=10000,
            ngram_range=ngram_range,
            stop_words="english",
            min_df=2,
            max_df=0.9,
            sublinear_tf=True,  # Use log(tf) for better scaling
        )

        self._is_fitted = False
        self._artifact_ids: List[int] = []
        self._tfidf_matrix: Any = None

    def _preprocess_text(self, text: Optional[str]) -> str:
        """
        Preprocess text for TF-IDF vectorization.

        - Lowercase
        - Remove special characters
        - Remove common dev-specific stop words
        - Normalize whitespace
        """
        if not text:
            return ""

        # Lowercase
        text = text.lower()

        # Remove URLs
        text = re.sub(r"https?://\S+", "", text)

        # Remove code blocks and inline code (common in technical docs)
        text = re.sub(r"```[\s\S]*?```", "", text)
        text = re.sub(r"`[^`]+`", "", text)

        # Remove special characters but keep alphanumeric and spaces
        text = re.sub(r"[^a-z0-9\s]", " ", text)

        # Remove dev-specific stop words
        words = text.split()
        words = [w for w in words if w not in self.DEV_STOP_WORDS]

        # Normalize whitespace
        text = " ".join(words)

        return text.strip()

    def _get_artifact_text(self, artifact: Artifact) -> str:
        """
        Extract text content from an artifact for similarity comparison.

        Combines title, external_id, and relevant metadata fields.
        """
        parts = []

        if artifact.title:
            parts.append(artifact.title)

        if artifact.display_key:
            parts.append(artifact.display_key)

        # Extract description from metadata if available
        if artifact.meta:
            meta = artifact.meta
            if isinstance(meta, dict):
                if "description" in meta:
                    parts.append(str(meta["description"]))
                if "summary" in meta:
                    parts.append(str(meta["summary"]))
                if "body" in meta:
                    parts.append(str(meta["body"]))
                if "content" in meta:
                    parts.append(str(meta["content"]))
                if "message" in meta:  # Git commit message
                    parts.append(str(meta["message"]))

        combined = " ".join(parts)
        return self._preprocess_text(combined)

    async def build_index(
        self,
        db: AsyncSession,
        project_id: Optional[int] = None,
        artifact_types: Optional[List[str]] = None,
    ) -> int:
        """
        Build TF-IDF index from artifacts in the database.

        Args:
            db: Database session
            project_id: Optional project filter
            artifact_types: Optional list of artifact types to include

        Returns:
            Number of artifacts indexed
        """
        query = select(Artifact)
        conditions = []

        if project_id:
            conditions.append(Artifact.project_id == project_id)

        if artifact_types:
            conditions.append(Artifact.type.in_(artifact_types))

        if conditions:
            query = query.where(and_(*conditions))

        result = await db.execute(query)
        artifacts = result.scalars().all()

        if not artifacts:
            logger.warning("No artifacts found for indexing")
            return 0

        # Extract texts and artifact IDs
        texts = []
        self._artifact_ids = []

        for artifact in artifacts:
            text = self._get_artifact_text(artifact)
            if text:  # Only include artifacts with text content
                texts.append(text)
                self._artifact_ids.append(artifact.id)

        if len(texts) < 2:
            logger.warning(f"Not enough artifacts with text content for TF-IDF: {len(texts)}")
            return len(texts)

        # Fit TF-IDF vectorizer
        try:
            self._tfidf_matrix = self.vectorizer.fit_transform(texts)
            self._is_fitted = True
            logger.info(
                f"Built TF-IDF index with {len(texts)} artifacts, vocabulary size: {len(self.vectorizer.vocabulary_)}"
            )
        except ValueError as e:
            logger.error(f"Failed to build TF-IDF index: {e}")
            return 0

        return len(texts)

    def find_similar(
        self,
        artifact_idx: int,
        top_k: int = 10,
    ) -> List[Tuple[int, float]]:
        """
        Find similar artifacts to the given artifact index.

        Args:
            artifact_idx: Index in the TF-IDF matrix
            top_k: Number of top similar artifacts to return

        Returns:
            List of (artifact_id, similarity_score) tuples
        """
        if not self._is_fitted or self._tfidf_matrix is None:
            return []

        # Get similarity scores for this artifact against all others
        artifact_vector = self._tfidf_matrix[artifact_idx]
        similarities = cosine_similarity(artifact_vector, self._tfidf_matrix).flatten()

        # Get top-k indices (excluding self)
        top_indices = np.argsort(similarities)[::-1]

        results: List[Tuple[int, float]] = []
        for idx in top_indices:
            if idx == artifact_idx:
                continue
            score = similarities[idx]
            if score < self.min_similarity:
                break
            if len(results) >= top_k:
                break
            results.append((self._artifact_ids[idx], float(score)))

        return results

    async def generate_suggestions(
        self,
        db: AsyncSession,
        project_id: Optional[int] = None,
        artifact_types: Optional[List[str]] = None,
        rebuild_index: bool = True,
    ) -> List[SimilarityResult]:
        """
        Generate link suggestions based on text similarity.

        Args:
            db: Database session
            project_id: Optional project filter
            artifact_types: Types of artifacts to analyze
            rebuild_index: Whether to rebuild the TF-IDF index

        Returns:
            List of similarity results for suggested links
        """
        if rebuild_index or not self._is_fitted:
            count = await self.build_index(db, project_id, artifact_types)
            if count < 2:
                return []

        # Get artifact type mapping
        query = select(Artifact.id, Artifact.type).where(Artifact.id.in_(self._artifact_ids))
        result = await db.execute(query)
        artifact_types_map: Dict[int, str] = {row[0]: row[1] for row in result}

        # Get existing links to avoid duplicates
        link_query = select(ArtifactLink.from_artifact_id, ArtifactLink.to_artifact_id)
        if project_id:
            link_query = link_query.where(ArtifactLink.project_id == project_id)
        link_result = await db.execute(link_query)
        existing_links = set((row[0], row[1]) for row in link_result)

        # Get existing suggestions to avoid duplicates
        sugg_query = select(SuggestedLink.from_artifact_id, SuggestedLink.to_artifact_id).where(
            SuggestedLink.status == "pending"
        )
        if project_id:
            sugg_query = sugg_query.where(SuggestedLink.project_id == project_id)
        sugg_result = await db.execute(sugg_query)
        existing_suggestions = set((row[0], row[1]) for row in sugg_result)

        # Build linkable type pairs lookup
        linkable_pairs: Dict[Tuple[str, str], str] = {}
        for from_type, to_type, link_type in self.LINKABLE_TYPE_PAIRS:
            linkable_pairs[(from_type, to_type)] = link_type
            # Also add reverse for bidirectional matching
            if (to_type, from_type) not in linkable_pairs:
                linkable_pairs[(to_type, from_type)] = link_type

        suggestions: List[SimilarityResult] = []

        # Find similar artifacts for each artifact
        for idx, artifact_id in enumerate(self._artifact_ids):
            artifact_type = artifact_types_map.get(artifact_id)
            if not artifact_type:
                continue

            similar = self.find_similar(idx, top_k=self.max_suggestions_per_artifact * 2)

            count = 0
            for similar_id, score in similar:
                # Skip if already linked or suggested
                if (artifact_id, similar_id) in existing_links:
                    continue
                if (similar_id, artifact_id) in existing_links:
                    continue
                if (artifact_id, similar_id) in existing_suggestions:
                    continue
                if (similar_id, artifact_id) in existing_suggestions:
                    continue

                similar_type = artifact_types_map.get(similar_id)
                if not similar_type:
                    continue

                # Check if this type pair is linkable
                type_pair = (artifact_type, similar_type)
                if type_pair not in linkable_pairs:
                    continue

                link_type = linkable_pairs[type_pair]

                suggestions.append(
                    SimilarityResult(
                        from_artifact_id=artifact_id,
                        to_artifact_id=similar_id,
                        similarity_score=score,
                        suggested_link_type=link_type,
                        reason=f"Text similarity score: {score:.2%} between {artifact_type} and {similar_type}",
                        method="tfidf",
                    )
                )

                count += 1
                if count >= self.max_suggestions_per_artifact:
                    break

        # Sort by similarity score descending
        suggestions.sort(key=lambda x: x.similarity_score, reverse=True)

        logger.info(f"Generated {len(suggestions)} link suggestions")
        return suggestions

    async def store_suggestions(
        self,
        db: AsyncSession,
        suggestions: List[SimilarityResult],
        project_id: Optional[int] = None,
        tenant_id: Optional[str] = None,
    ) -> int:
        """
        Store generated suggestions in the database.

        Args:
            db: Database session
            suggestions: List of similarity results
            project_id: Project ID for the suggestions
            tenant_id: Tenant ID for multi-tenancy

        Returns:
            Number of suggestions stored
        """
        stored = 0

        for sugg in suggestions:
            suggested_link = SuggestedLink(
                tenant_id=tenant_id,
                project_id=project_id,
                from_artifact_id=sugg.from_artifact_id,
                to_artifact_id=sugg.to_artifact_id,
                suggested_link_type=sugg.suggested_link_type,
                similarity_score=sugg.similarity_score,
                method=sugg.method,
                reason=sugg.reason,
                status="pending",
            )
            db.add(suggested_link)
            stored += 1

        try:
            await db.commit()
            logger.info(f"Stored {stored} link suggestions")
        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to store suggestions: {e}")
            return 0

        return stored

    async def find_similar_to_artifact(
        self,
        db: AsyncSession,
        artifact_id: int,
        top_k: int = 10,
    ) -> List[Tuple[int, float]]:
        """
        Find artifacts similar to a specific artifact.

        This is a convenience method for finding similar artifacts
        when you have a specific artifact ID.

        Args:
            db: Database session
            artifact_id: ID of the artifact to find similar matches for
            top_k: Number of similar artifacts to return

        Returns:
            List of (artifact_id, similarity_score) tuples
        """
        if not self._is_fitted:
            # Build index if not already done
            artifact = await db.get(Artifact, artifact_id)
            if not artifact:
                return []
            await self.build_index(db, artifact.project_id)

        if artifact_id not in self._artifact_ids:
            return []

        idx = self._artifact_ids.index(artifact_id)
        return self.find_similar(idx, top_k)


# Singleton instance
_similarity_service: Optional[TextSimilarityService] = None


def get_similarity_service() -> TextSimilarityService:
    """Get or create the singleton similarity service."""
    global _similarity_service
    if _similarity_service is None:
        _similarity_service = TextSimilarityService()
    return _similarity_service
