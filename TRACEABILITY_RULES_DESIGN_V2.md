# Traceability Rules Engine - Design Document v2.0

**Updated:** 2025-10-05
**Based on:** Industry research (Jama, Polarion, IBM DOORS) + Atlassian best practices

---

## Проблема

Текущая система автоматического связывания артефактов:
- Жёстко закодирована логика поиска Jira ключей в коммитах
- Не учитывает иерархию User Story → Sub-task → Commit
- Не связывает Confluence страницы с Jira issues
- **80% коммитов остаются несвязанными** (198/990 links)
- Нет уверенности в качестве автоматически созданных связей

## Требуемая логика (WaBank)

```
Confluence Page (User Story описание)
    ↓ documents (95% confidence)
Jira Issue [User Story]
    ↓↑ parent_of / child_of (100% confidence, bidirectional)
Jira Issue [Sub-task] (Dev/QA tasks)
    ↓ implements (90% confidence)
Git Commit (WAB-123 в сообщении)
    ↓ tested_by (85% confidence)
Test Case / Test Run
```

---

## Ключевые улучшения v2.0

### 1. Bidirectional Traceability ✨ NEW
- Forward: Requirement → Code → Test
- Backward: Test → Code → Requirement
- Автоматическое создание обратных связей

### 2. Confidence Score Tiers ✨ NEW
| Tier | Range | Action | Example |
|------|-------|--------|---------|
| **High** | 85-100% | Auto-accept | API parent link (100%) |
| **Medium** | 50-84% | Manual review queue | Fuzzy title match (70%) |
| **Low** | 0-49% | Reject or flag | Weak regex match (30%) |

### 3. Transitive Linking ✨ NEW
```python
# Автоматически создать:
Commit --implements--> Sub-task --child_of--> User Story
# Результат:
Commit --derives_from--> User Story (confidence = min(90%, 100%) = 90%)
```

### 4. Modern Jira Regex ✨ UPDATED
```python
# Старый паттерн (v1):
r"([A-Z]+-\d+)"  # Только буквы в project key

# Новый паттерн (v2, Jira 2015+):
r"\b[A-Z][A-Z0-9_]+-[0-9]+\b"  # Поддержка цифр и подчёркиваний
# Пример: "ABC123_PRJ-456" ✅
```

### 5. Conflict Resolution ✨ NEW
- Если несколько правил создают разные связи → приоритет по priority
- Если одно правило создаёт дубликаты → обновить confidence
- Аудит лог всех изменений связей

---

## 1. Enhanced Data Models

### 1.1 TraceabilityRule

```python
# backend/app/models/traceability_rules.py

from sqlalchemy import Column, Integer, String, JSON, Boolean, ForeignKey, Enum, DateTime
from sqlalchemy.sql import func
from app.core.database import Base
import enum

class LinkDirection(str, enum.Enum):
    FORWARD = "forward"           # A → B
    BACKWARD = "backward"         # B ← A
    BIDIRECTIONAL = "bidirectional"  # A ↔ B

class MatchStrategy(str, enum.Enum):
    JIRA_KEY = "jira_key"         # [A-Z0-9_]+-[0-9]+
    REGEX = "regex"               # Custom regex
    TITLE_MATCH = "title_match"   # Fuzzy matching (Levenshtein)
    API_LINK = "api_link"         # Direct API link (parent, issuelinks)
    CUSTOM_FIELD = "custom_field" # JSON path extraction
    NLP_SIMILARITY = "nlp_similarity"  # Future: BERT embeddings

class ConfidenceTier(str, enum.Enum):
    HIGH = "high"      # 85-100%: auto-accept
    MEDIUM = "medium"  # 50-84%: manual review
    LOW = "low"        # 0-49%: reject or flag

class TraceabilityRule(Base):
    """Правило автоматического связывания артефактов."""
    __tablename__ = "traceability_rules"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)

    # Metadata
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    enabled = Column(Boolean, default=True)
    priority = Column(Integer, default=100)  # Lower = higher priority
    version = Column(Integer, default=1)  # ✨ NEW: Rule versioning

    # Artifact types
    source_artifact_type = Column(String, nullable=False)
    target_artifact_type = Column(String, nullable=False)

    # Match strategy
    match_strategy = Column(Enum(MatchStrategy), nullable=False)
    match_config = Column(JSON, nullable=False)

    # Filters
    source_filter = Column(JSON, nullable=True)
    target_filter = Column(JSON, nullable=True)

    # Link configuration
    link_type = Column(String, default="relates_to")
    link_direction = Column(Enum(LinkDirection), default=LinkDirection.FORWARD)

    # ✨ NEW: Create reverse link automatically?
    create_reverse_link = Column(Boolean, default=False)
    reverse_link_type = Column(String, nullable=True)  # e.g., "child_of" → "parent_of"

    # Confidence
    base_confidence = Column(Integer, default=80)
    confidence_tier = Column(Enum(ConfidenceTier), default=ConfidenceTier.MEDIUM)
    confidence_factors = Column(JSON, nullable=True)

    # ✨ NEW: Transitive linking
    enable_transitive = Column(Boolean, default=False)
    transitive_config = Column(JSON, nullable=True)  # {"max_depth": 2, "strategies": [...]}

    # ✨ NEW: Manual review
    require_manual_review = Column(Boolean, default=False)
    review_threshold = Column(Integer, default=50)  # Confidence below this → queue

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
```

### 1.2 ArtifactLink (Enhanced)

```python
# backend/app/models/traceability.py - UPDATE

class ArtifactLink(Base):
    __tablename__ = "artifact_links"

    id = Column(Integer, primary_key=True)
    source_artifact_id = Column(Integer, ForeignKey("artifacts.id"), nullable=False, index=True)
    target_artifact_id = Column(Integer, ForeignKey("artifacts.id"), nullable=False, index=True)

    link_type = Column(String, default="relates_to")
    confidence_score = Column(Integer, default=100)

    # ✨ NEW: Review workflow
    status = Column(Enum(LinkStatus), default=LinkStatus.AUTO_CREATED)
    reviewed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    review_note = Column(String, nullable=True)

    # ✨ NEW: Provenance
    created_by_rule_id = Column(Integer, ForeignKey("traceability_rules.id"), nullable=True, index=True)
    rule_version = Column(Integer, nullable=True)  # Rule version at creation time
    is_manual = Column(Boolean, default=False)

    # ✨ NEW: Transitive link tracking
    is_transitive = Column(Boolean, default=False)
    transitive_path = Column(JSON, nullable=True)  # [link_id1, link_id2, ...]

    metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class LinkStatus(str, enum.Enum):
    AUTO_CREATED = "auto_created"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    MANUAL = "manual"
```

### 1.3 LinkReview (Manual Review Queue)

```python
class LinkReview(Base):
    """Queue for manual review of medium-confidence links."""
    __tablename__ = "link_reviews"

    id = Column(Integer, primary_key=True)
    link_id = Column(Integer, ForeignKey("artifact_links.id"), nullable=False, index=True)

    assigned_to_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    priority = Column(Integer, default=50)  # Based on confidence gap

    review_context = Column(JSON, nullable=True)  # Why this needs review
    decision = Column(Enum(ReviewDecision), nullable=True)
    decision_note = Column(String, nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ReviewDecision(str, enum.Enum):
    APPROVE = "approve"
    REJECT = "reject"
    ADJUST_CONFIDENCE = "adjust_confidence"
    ESCALATE = "escalate"
```

---

## 2. Updated Rule Templates

### 2.1 Commit → Sub-task (Enhanced)

```python
{
    "name": "Commit → Jira Sub-task (via JIRA key, modern)",
    "source_artifact_type": "Commit",
    "target_artifact_type": "JiraIssue",
    "match_strategy": "jira_key",
    "match_config": {
        "search_in": ["message", "branch_name"],
        # ✨ UPDATED: Modern Jira pattern (supports numbers/underscores in project key)
        "pattern": r"\b[A-Z][A-Z0-9_]+-[0-9]+\b",
        "case_sensitive": False,
        "must_be_uppercase": True
    },
    "target_filter": {
        "jira_issue_type": ["Sub-task", "Task", "Bug"]
    },
    "link_type": "implements",
    "base_confidence": 90,
    "confidence_tier": "high",

    # ✨ NEW: Bidirectional
    "create_reverse_link": True,
    "reverse_link_type": "implemented_by",

    # ✨ NEW: Confidence boosters
    "confidence_factors": {
        "key_at_start": +10,      # "WAB-123: Fix bug" → 100%
        "multiple_keys": -5,      # Multiple keys → slightly lower
        "branch_name_match": +5   # Key in both message AND branch
    }
}
```

### 2.2 Sub-task → User Story (Parent Link)

```python
{
    "name": "Sub-task → User Story (via API parent link)",
    "source_artifact_type": "JiraIssue",
    "target_artifact_type": "JiraIssue",
    "match_strategy": "api_link",
    "match_config": {
        "jira_field": "parent",  # issue.fields.parent.key
        "api_path": "$.fields.parent.key"
    },
    "source_filter": {
        "jira_issue_type": ["Sub-task"]
    },
    "target_filter": {
        "jira_issue_type": ["Story", "User Story"]
    },
    "link_type": "child_of",
    "base_confidence": 100,  # API link = always 100%
    "confidence_tier": "high",

    # ✨ NEW: Bidirectional
    "create_reverse_link": True,
    "reverse_link_type": "parent_of"
}
```

### 2.3 Confluence → User Story (Multi-strategy)

```python
{
    "name": "Confluence Page → User Story (composite strategy)",
    "source_artifact_type": "ConfluencePage",
    "target_artifact_type": "JiraIssue",
    "match_strategy": "composite",  # ✨ NEW: Try multiple strategies
    "match_config": {
        "strategies": [
            {
                "type": "custom_field",
                "search_in": "body",
                "pattern": r'ac:parameter ac:name="key">([A-Z][A-Z0-9_]+-[0-9]+)</ac:parameter',
                "extract_group": 1,
                "confidence": 95
            },
            {
                "type": "jira_key",
                "search_in": ["title", "body"],
                "pattern": r"\b[A-Z][A-Z0-9_]+-[0-9]+\b",
                "confidence": 85
            },
            {
                "type": "title_match",
                "similarity_threshold": 0.75,
                "confidence": 70
            }
        ],
        "use_best_match": True  # Pick strategy with highest confidence
    },
    "target_filter": {
        "jira_issue_type": ["Story", "User Story", "Epic"]
    },
    "link_type": "documents",
    "base_confidence": 85,
    "confidence_tier": "high",

    "create_reverse_link": True,
    "reverse_link_type": "documented_by"
}
```

---

## 3. Transitive Linking Engine

### 3.1 Configuration

```python
{
    "enable_transitive": True,
    "transitive_config": {
        "max_depth": 2,  # Commit → Sub-task → User Story (2 hops)
        "min_confidence": 70,  # Don't create transitive if any link < 70%
        "strategies": [
            {
                "path": ["implements", "child_of"],
                "result_link_type": "derives_from",
                "confidence_formula": "min"  # min(90, 100) = 90%
            },
            {
                "path": ["tested_by", "implements"],
                "result_link_type": "validates",
                "confidence_formula": "average"
            }
        ]
    }
}
```

### 3.2 Example

```
Given:
  Commit#1 --implements--> SubTask#2 (confidence=90%)
  SubTask#2 --child_of--> UserStory#3 (confidence=100%)

Auto-create:
  Commit#1 --derives_from--> UserStory#3 (confidence=90%, transitive=True)
```

---

## 4. Confidence Scoring Formula

### 4.1 Calculation

```python
def calculate_confidence(
    base_confidence: int,
    factors: dict,
    match_quality: float
) -> tuple[int, ConfidenceTier]:
    """
    Calculate final confidence score with factors.

    Args:
        base_confidence: Rule's base confidence
        factors: Dict of factor_name → weight
        match_quality: 0.0-1.0 from matching algorithm

    Returns:
        (final_score, tier)
    """
    score = base_confidence

    # Apply factors
    for factor, weight in factors.items():
        if factor_applies(factor):
            score += weight

    # Apply match quality
    score = int(score * match_quality)

    # Clamp to 0-100
    score = max(0, min(100, score))

    # Determine tier
    if score >= 85:
        tier = ConfidenceTier.HIGH
    elif score >= 50:
        tier = ConfidenceTier.MEDIUM
    else:
        tier = ConfidenceTier.LOW

    return score, tier
```

### 4.2 Confidence Factors

| Factor | Weight | Condition |
|--------|--------|-----------|
| `key_at_start` | +10 | Jira key is first word in commit message |
| `multiple_keys` | -5 | Multiple different keys found |
| `branch_name_match` | +5 | Key in both message AND branch |
| `exact_title_match` | +15 | Titles are identical |
| `high_similarity` | +10 | Title similarity > 0.9 |
| `api_verified` | +20 | Link exists in source system API |

---

## 5. Conflict Resolution Strategy

### 5.1 Scenarios

**Scenario 1: Multiple rules create same link**
```
Rule A (priority=10): Commit → Sub-task, confidence=90%
Rule B (priority=20): Commit → Sub-task, confidence=85%

Resolution: Keep Rule A (higher priority), update confidence to max(90, 85) = 90%
```

**Scenario 2: Different link types**
```
Rule A: Commit → Issue, link_type="implements"
Rule B: Commit → Issue, link_type="relates_to"

Resolution: Keep both (different semantics)
```

**Scenario 3: Circular dependency**
```
A --parent_of--> B
B --parent_of--> A  ❌

Resolution: Reject second link, log error
```

### 5.2 Implementation

```python
class ConflictResolution(str, enum.Enum):
    KEEP_HIGHER_PRIORITY = "keep_higher_priority"
    KEEP_HIGHER_CONFIDENCE = "keep_higher_confidence"
    KEEP_BOTH = "keep_both"
    MERGE_METADATA = "merge_metadata"
    MANUAL_REVIEW = "manual_review"
```

---

## 6. Performance Optimizations

### 6.1 Indexing Strategy

```sql
-- Add composite indexes for fast lookups
CREATE INDEX idx_artifacts_type_external_id
ON artifacts(artifact_type, external_id);

CREATE INDEX idx_artifacts_type_title
ON artifacts(artifact_type, title);

CREATE INDEX idx_links_source_target
ON artifact_links(source_artifact_id, target_artifact_id, link_type);

CREATE INDEX idx_links_rule_created
ON artifact_links(created_by_rule_id, created_at);
```

### 6.2 Batch Processing

```python
async def apply_rule_batch(
    rule: TraceabilityRule,
    source_ids: List[int],
    batch_size: int = 100
) -> Stats:
    """Process sources in batches."""
    total_created = 0

    for i in range(0, len(source_ids), batch_size):
        batch = source_ids[i:i+batch_size]

        # Fetch sources in bulk
        sources = await db.execute(
            select(Artifact).where(Artifact.id.in_(batch))
        )

        # Pre-load potential targets (with filters)
        target_candidates = await _preload_targets(rule)

        # Match in memory (fast)
        matches = []
        for source in sources:
            for target in target_candidates:
                if _matches(rule, source, target):
                    matches.append((source, target))

        # Bulk insert links
        if matches:
            await db.execute(
                insert(ArtifactLink),
                [_create_link_dict(s, t, rule) for s, t in matches]
            )
            total_created += len(matches)

    return {"created": total_created}
```

### 6.3 Incremental Updates

```python
# Only process artifacts changed since last run
last_run = rule.metadata.get("last_run_at")

new_artifacts = await db.execute(
    select(Artifact)
    .where(
        Artifact.artifact_type == rule.source_artifact_type,
        Artifact.created_at > last_run  # ✨ Only new
    )
)
```

---

## 7. Manual Review Workflow

### 7.1 UI Mockup

```
┌─ Manual Review Queue ────────────────────────────────┐
│  198 links pending review (sorted by priority)       │
├──────────────────────────────────────────────────────┤
│                                                       │
│  [HIGH PRIORITY] Commit#1 → Issue#2                  │
│  Link: "implements" | Confidence: 72%                │
│  Reason: Fuzzy title match (similarity=0.72)         │
│                                                       │
│  Source: "feat: add user authentication"             │
│  Target: "[WAB-123] Implement user auth system"      │
│                                                       │
│  [✓ Approve] [✗ Reject] [Edit Confidence ▼]         │
│  Note: ________________________________              │
│                                                       │
├──────────────────────────────────────────────────────┤
│  Actions:                                             │
│  • Bulk approve high-similarity (>80%): 45 links     │
│  • Assign to me: All WAB-* links                     │
│  • Export for review: CSV                            │
└──────────────────────────────────────────────────────┘
```

### 7.2 Workflow States

```
Auto-created (confidence < threshold)
    ↓
Pending Review (assigned to user/team)
    ↓
[User Decision]
    ├→ Approved → Active link
    ├→ Rejected → Archived
    ├→ Adjusted → Update confidence, re-queue
    └→ Escalated → Manager review
```

---

## 8. Implementation Phases

### Phase 1: Core Engine (2 weeks)
- [ ] Create migrations for new tables
- [ ] Implement TraceabilityRule model
- [ ] Implement RuleEngine with `jira_key` + `api_link` strategies
- [ ] Basic UI: rule list + create from templates
- [ ] API endpoints: `/rules`, `/rules/apply`
- **Goal:** Replace hardcoded logic, achieve 60% link coverage

### Phase 2: Confidence & Review (1 week)
- [ ] Implement confidence scoring with tiers
- [ ] Create LinkReview queue
- [ ] UI for manual review workflow
- [ ] Bulk review actions
- **Goal:** High-quality links, manual validation for medium-confidence

### Phase 3: Bidirectional & Transitive (1 week)
- [ ] Implement bidirectional link creation
- [ ] Transitive linking engine
- [ ] Conflict resolution logic
- [ ] Performance optimization (indexing, batch processing)
- **Goal:** Complete chain visibility (Confluence → Commit)

### Phase 4: Advanced Strategies (2 weeks)
- [ ] `title_match` with Levenshtein distance
- [ ] `composite` strategy (try multiple, pick best)
- [ ] `nlp_similarity` (TF-IDF or BERT embeddings)
- [ ] A/B testing framework for strategies
- **Goal:** 90%+ link coverage with high accuracy

---

## 9. Success Metrics

| Metric | Current | Phase 1 Goal | Phase 4 Goal |
|--------|---------|--------------|--------------|
| Link Coverage | 20% (198/990) | 60% (594/990) | 90% (891/990) |
| High-Confidence Links | Unknown | 70% auto-approved | 85% auto-approved |
| Manual Review Queue | N/A | <100 items/week | <20 items/week |
| False Positives | Unknown | <5% | <2% |
| Processing Time | N/A | <5 min for 1k artifacts | <1 min for 1k artifacts |

---

## 10. Migration Plan

### From Current System

```python
# Step 1: Create default rule from existing logic
migration_rule = TraceabilityRule(
    name="Legacy: Commit → Jira (any type)",
    source_artifact_type="Commit",
    target_artifact_type="JiraIssue",
    match_strategy=MatchStrategy.JIRA_KEY,
    match_config={
        "search_in": ["message"],
        "pattern": r"([A-Z]+-\d+)"  # Old pattern
    },
    base_confidence=80,
    enabled=False  # Don't auto-apply, migrate manually
)

# Step 2: Mark existing links as migrated
UPDATE artifact_links
SET created_by_rule_id = migration_rule.id,
    is_manual = FALSE,
    metadata = jsonb_set(metadata, '{migrated}', 'true')
WHERE created_by_rule_id IS NULL;

# Step 3: Create new rules with improved patterns
# Step 4: Apply new rules to new artifacts only
# Step 5: Gradually re-apply to old artifacts in batches
```

---

## 11. Open Questions for Discussion

1. **Transitive link depth:** Max 2 hops or configurable?
2. **Confidence threshold for auto-apply:** 85% or 80%?
3. **Manual review SLA:** Who reviews? Within 24h/48h/1 week?
4. **Rule versioning:** Re-apply when rule changes? Or only to new artifacts?
5. **Circular dependency handling:** Reject or allow with warning?
6. **Performance target:** Process 10k artifacts in <5 min acceptable?

---

## Appendix: Research Sources

- [Inflectra: Requirements Traceability Best Practices](https://www.inflectra.com/Ideas/Topic/Requirements-Traceability.aspx)
- [Visure: RTM Tools 2024](https://visuresolutions.com/blog/traceability-matrix/)
- [Atlassian: Jira Automation](https://support.atlassian.com/cloud-automation/docs/jira-automation-actions/)
- [Stack Overflow: Jira Regex Patterns](https://stackoverflow.com/questions/19322669/regular-expression-for-a-jira-identifier)
- Polarion ALM Documentation
- Academic papers on automated traceability (F1-score 79-80%)
