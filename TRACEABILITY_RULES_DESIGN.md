# Traceability Rules Engine - Design Document

## Проблема

Текущая система автоматического связывания артефактов:
- Жёстко закодирована логика поиска Jira ключей в коммитах
- Не учитывает иерархию User Story → Sub-task → Commit
- Не связывает Confluence страницы с Jira issues
- 80% коммитов остаются несвязанными

## Требуемая логика (пример WaBank)

```
Confluence Page (User Story описание)
    ↓ implements
Jira Issue [User Story]
    ↓ has subtasks
Jira Issue [Sub-task] (Dev/QA tasks)
    ↓ mentioned in
Git Commit (с упоминанием JIRA-123 в сообщении)
    ↓ tested by
Test Case / Test Run
```

## Решение: Rule-Based Traceability Engine

### 1. Модель данных: TraceabilityRule

```python
# backend/app/models/traceability_rules.py

from sqlalchemy import Column, Integer, String, JSON, Boolean, ForeignKey, Enum
from app.core.database import Base
import enum

class LinkDirection(str, enum.Enum):
    FORWARD = "forward"   # A → B
    BACKWARD = "backward" # A ← B
    BIDIRECTIONAL = "bidirectional"  # A ↔ B

class MatchStrategy(str, enum.Enum):
    REGEX = "regex"               # Регулярное выражение
    JIRA_KEY = "jira_key"         # Поиск JIRA-123 паттерна
    TITLE_MATCH = "title_match"   # Совпадение заголовков
    CUSTOM_FIELD = "custom_field" # Специальное поле
    API_LINK = "api_link"         # Прямая ссылка через API (issue.fields.parent)

class TraceabilityRule(Base):
    """Правило автоматического связывания артефактов."""
    __tablename__ = "traceability_rules"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)  # None = глобальное

    # Описание
    name = Column(String, nullable=False)  # "Commit → Sub-task via JIRA key"
    description = Column(String, nullable=True)
    enabled = Column(Boolean, default=True)
    priority = Column(Integer, default=100)  # Порядок применения (меньше = раньше)

    # Источник и целевой тип артефакта
    source_artifact_type = Column(String, nullable=False)  # "Commit", "JiraIssue", "ConfluencePage"
    target_artifact_type = Column(String, nullable=False)  # "JiraIssue", "TestCase", etc.

    # Стратегия поиска связи
    match_strategy = Column(Enum(MatchStrategy), nullable=False)
    match_config = Column(JSON, nullable=False)  # Конфигурация для стратегии

    # Дополнительные фильтры
    source_filter = Column(JSON, nullable=True)  # {"jira_issue_type": "Sub-task"}
    target_filter = Column(JSON, nullable=True)  # {"jira_issue_type": "User Story"}

    # Тип связи
    link_type = Column(String, default="relates_to")  # implements, tests, derives_from, etc.
    link_direction = Column(Enum(LinkDirection), default=LinkDirection.FORWARD)

    # Confidence scoring
    base_confidence = Column(Integer, default=80)  # Базовая уверенность 0-100
    confidence_factors = Column(JSON, nullable=True)  # Дополнительные факторы

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
```

### 2. Предустановленные правила (Rule Templates)

```python
# backend/app/services/traceability/rule_templates.py

RULE_TEMPLATES = {
    "commit_to_subtask_jira_key": {
        "name": "Commit → Jira Sub-task (via JIRA key in message)",
        "source_artifact_type": "Commit",
        "target_artifact_type": "JiraIssue",
        "match_strategy": "jira_key",
        "match_config": {
            "search_in": ["message", "branch_name"],
            "pattern": r"(?:JIRA-|WAB-|PRIM-)(\d+)",
            "case_sensitive": False
        },
        "target_filter": {
            "jira_issue_type": ["Sub-task", "Task", "Bug"]
        },
        "link_type": "implements",
        "base_confidence": 90
    },

    "subtask_to_user_story_parent": {
        "name": "Jira Sub-task → User Story (via parent link)",
        "source_artifact_type": "JiraIssue",
        "target_artifact_type": "JiraIssue",
        "match_strategy": "api_link",
        "match_config": {
            "jira_field": "parent",  # issue.fields.parent.key
            "link_type": "parent"
        },
        "source_filter": {
            "jira_issue_type": ["Sub-task"]
        },
        "target_filter": {
            "jira_issue_type": ["Story", "User Story"]
        },
        "link_type": "child_of",
        "base_confidence": 100
    },

    "confluence_to_user_story_title": {
        "name": "Confluence Page → User Story (via title match)",
        "source_artifact_type": "ConfluencePage",
        "target_artifact_type": "JiraIssue",
        "match_strategy": "title_match",
        "match_config": {
            "similarity_threshold": 0.7,  # Levenshtein distance
            "normalize": True,
            "extract_jira_key": True  # Поиск JIRA-123 в заголовке Confluence
        },
        "target_filter": {
            "jira_issue_type": ["Story", "User Story"]
        },
        "link_type": "documents",
        "base_confidence": 75
    },

    "confluence_to_user_story_jira_macro": {
        "name": "Confluence Page → User Story (via Jira macro)",
        "source_artifact_type": "ConfluencePage",
        "target_artifact_type": "JiraIssue",
        "match_strategy": "custom_field",
        "match_config": {
            "search_in": "body",
            "pattern": r'ac:parameter ac:name="key">([A-Z]+-\d+)</ac:parameter',
            "extract_group": 1
        },
        "link_type": "documents",
        "base_confidence": 95
    },

    "user_story_to_confluence_links": {
        "name": "User Story → Confluence Page (via Web Links)",
        "source_artifact_type": "JiraIssue",
        "target_artifact_type": "ConfluencePage",
        "match_strategy": "api_link",
        "match_config": {
            "jira_field": "issuelinks",  # Remote links
            "link_url_pattern": r"confluence\..*\/pages\/(\d+)"
        },
        "source_filter": {
            "jira_issue_type": ["Story", "User Story"]
        },
        "link_type": "documented_by",
        "base_confidence": 100
    }
}
```

### 3. Rule Engine - применение правил

```python
# backend/app/services/traceability/rule_engine.py

from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import re
from difflib import SequenceMatcher

from app.models.traceability import Artifact, ArtifactLink
from app.models.traceability_rules import TraceabilityRule, MatchStrategy

class TraceabilityRuleEngine:
    """Движок для применения правил связывания артефактов."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def apply_rules(
        self,
        project_id: Optional[int] = None,
        artifact_ids: Optional[List[int]] = None,
        rule_ids: Optional[List[int]] = None
    ) -> Dict[str, Any]:
        """
        Применить правила связывания к артефактам.

        Args:
            project_id: ID проекта (если None - все проекты)
            artifact_ids: Конкретные артефакты (если None - все)
            rule_ids: Конкретные правила (если None - все enabled)
        """
        # Загрузить правила
        rules = await self._load_rules(project_id, rule_ids)

        stats = {
            "rules_applied": 0,
            "links_created": 0,
            "links_updated": 0,
            "artifacts_processed": 0,
            "errors": []
        }

        for rule in rules:
            try:
                result = await self._apply_single_rule(rule, project_id, artifact_ids)
                stats["rules_applied"] += 1
                stats["links_created"] += result["created"]
                stats["links_updated"] += result["updated"]
                stats["artifacts_processed"] += result["processed"]
            except Exception as e:
                stats["errors"].append({
                    "rule_id": rule.id,
                    "rule_name": rule.name,
                    "error": str(e)
                })

        return stats

    async def _load_rules(
        self,
        project_id: Optional[int],
        rule_ids: Optional[List[int]]
    ) -> List[TraceabilityRule]:
        """Загрузить правила с учётом фильтров."""
        query = select(TraceabilityRule).where(TraceabilityRule.enabled == True)

        if project_id:
            # Глобальные правила + правила проекта
            query = query.where(
                (TraceabilityRule.project_id == project_id) |
                (TraceabilityRule.project_id.is_(None))
            )

        if rule_ids:
            query = query.where(TraceabilityRule.id.in_(rule_ids))

        query = query.order_by(TraceabilityRule.priority.asc())

        result = await self.db.execute(query)
        return result.scalars().all()

    async def _apply_single_rule(
        self,
        rule: TraceabilityRule,
        project_id: Optional[int],
        artifact_ids: Optional[List[int]]
    ) -> Dict[str, int]:
        """Применить одно правило."""
        # Найти source артефакты
        sources = await self._find_artifacts(
            artifact_type=rule.source_artifact_type,
            project_id=project_id,
            artifact_ids=artifact_ids,
            filters=rule.source_filter
        )

        created = 0
        updated = 0

        for source in sources:
            # Для каждого source найти target'ы по стратегии
            targets = await self._match_targets(rule, source)

            for target, confidence in targets:
                link_created = await self._create_or_update_link(
                    source=source,
                    target=target,
                    link_type=rule.link_type,
                    confidence=confidence,
                    rule_id=rule.id
                )
                if link_created:
                    created += 1
                else:
                    updated += 1

        return {"created": created, "updated": updated, "processed": len(sources)}

    async def _match_targets(
        self,
        rule: TraceabilityRule,
        source: Artifact
    ) -> List[tuple[Artifact, int]]:
        """Найти target артефакты для source по стратегии правила."""
        strategy = rule.match_strategy

        if strategy == MatchStrategy.JIRA_KEY:
            return await self._match_by_jira_key(rule, source)
        elif strategy == MatchStrategy.REGEX:
            return await self._match_by_regex(rule, source)
        elif strategy == MatchStrategy.TITLE_MATCH:
            return await self._match_by_title(rule, source)
        elif strategy == MatchStrategy.API_LINK:
            return await self._match_by_api_link(rule, source)
        elif strategy == MatchStrategy.CUSTOM_FIELD:
            return await self._match_by_custom_field(rule, source)

        return []

    async def _match_by_jira_key(
        self,
        rule: TraceabilityRule,
        source: Artifact
    ) -> List[tuple[Artifact, int]]:
        """Стратегия: поиск JIRA ключей в тексте."""
        config = rule.match_config
        pattern = config.get("pattern", r"([A-Z]+-\d+)")
        search_fields = config.get("search_in", ["message"])

        # Извлечь текст из source
        text_parts = []
        for field in search_fields:
            if field == "message" and source.artifact_type == "Commit":
                text_parts.append(source.metadata.get("message", ""))
            elif field == "branch_name" and source.artifact_type == "Commit":
                text_parts.append(source.metadata.get("branch", ""))
            elif field == "title":
                text_parts.append(source.title or "")

        full_text = " ".join(text_parts)

        # Найти все JIRA ключи
        jira_keys = re.findall(pattern, full_text, re.IGNORECASE)
        if not jira_keys:
            return []

        # Найти артефакты с этими ключами
        targets = []
        for jira_key in set(jira_keys):  # Уникальные ключи
            # Поиск Jira Issue артефакта с external_id = jira_key
            query = select(Artifact).where(
                Artifact.artifact_type == rule.target_artifact_type,
                Artifact.external_id == jira_key.upper()
            )

            # Применить target_filter
            if rule.target_filter:
                issue_type_filter = rule.target_filter.get("jira_issue_type")
                if issue_type_filter:
                    # Нужно проверить metadata.issue_type
                    query = query.where(
                        Artifact.metadata["issue_type"].astext.in_(issue_type_filter)
                    )

            result = await self.db.execute(query)
            target = result.scalar_one_or_none()

            if target:
                # Confidence = базовая + бонусы
                confidence = rule.base_confidence

                # Бонус если ключ в начале сообщения
                if full_text.strip().startswith(jira_key):
                    confidence = min(100, confidence + 10)

                targets.append((target, confidence))

        return targets

    async def _match_by_api_link(
        self,
        rule: TraceabilityRule,
        source: Artifact
    ) -> List[tuple[Artifact, int]]:
        """Стратегия: прямая ссылка через API (parent, issuelinks)."""
        config = rule.match_config
        jira_field = config.get("jira_field")

        if not jira_field or source.artifact_type != "JiraIssue":
            return []

        # Извлечь значение из metadata
        if jira_field == "parent":
            parent_key = source.metadata.get("parent_key")
            if not parent_key:
                return []

            # Найти артефакт с external_id = parent_key
            query = select(Artifact).where(
                Artifact.artifact_type == "JiraIssue",
                Artifact.external_id == parent_key
            )

            result = await self.db.execute(query)
            target = result.scalar_one_or_none()

            if target:
                return [(target, 100)]  # Прямая ссылка = 100% confidence

        return []

    async def _match_by_title(
        self,
        rule: TraceabilityRule,
        source: Artifact
    ) -> List[tuple[Artifact, int]]:
        """Стратегия: совпадение заголовков (fuzzy matching)."""
        config = rule.match_config
        threshold = config.get("similarity_threshold", 0.7)
        extract_jira = config.get("extract_jira_key", False)

        source_title = source.title or ""
        if not source_title:
            return []

        # Если включено extract_jira_key, сначала попробовать найти по ключу
        if extract_jira:
            jira_keys = re.findall(r"([A-Z]+-\d+)", source_title)
            if jira_keys:
                # Использовать jira_key стратегию
                temp_rule = TraceabilityRule(
                    match_strategy=MatchStrategy.JIRA_KEY,
                    match_config={"pattern": r"([A-Z]+-\d+)", "search_in": ["title"]},
                    target_artifact_type=rule.target_artifact_type,
                    target_filter=rule.target_filter,
                    base_confidence=rule.base_confidence
                )
                return await self._match_by_jira_key(temp_rule, source)

        # Fuzzy matching по заголовкам
        query = select(Artifact).where(
            Artifact.artifact_type == rule.target_artifact_type,
            Artifact.title.isnot(None)
        )

        result = await self.db.execute(query)
        candidates = result.scalars().all()

        matches = []
        for candidate in candidates:
            similarity = SequenceMatcher(None, source_title, candidate.title).ratio()
            if similarity >= threshold:
                confidence = int(similarity * rule.base_confidence)
                matches.append((candidate, confidence))

        # Сортировать по confidence (лучшие первые)
        matches.sort(key=lambda x: x[1], reverse=True)

        return matches[:10]  # Топ-10 совпадений

    async def _create_or_update_link(
        self,
        source: Artifact,
        target: Artifact,
        link_type: str,
        confidence: int,
        rule_id: int
    ) -> bool:
        """Создать или обновить связь."""
        # Проверить существующую связь
        query = select(ArtifactLink).where(
            ArtifactLink.source_artifact_id == source.id,
            ArtifactLink.target_artifact_id == target.id,
            ArtifactLink.link_type == link_type
        )

        result = await self.db.execute(query)
        existing = result.scalar_one_or_none()

        if existing:
            # Обновить confidence если новое значение выше
            if confidence > existing.confidence_score:
                existing.confidence_score = confidence
                existing.metadata = existing.metadata or {}
                existing.metadata["rule_id"] = rule_id
                await self.db.commit()
            return False  # Не создали новую связь
        else:
            # Создать новую связь
            link = ArtifactLink(
                source_artifact_id=source.id,
                target_artifact_id=target.id,
                link_type=link_type,
                confidence_score=confidence,
                metadata={"rule_id": rule_id, "auto_created": True}
            )
            self.db.add(link)
            await self.db.commit()
            return True  # Создали новую связь
```

### 4. UI: Rule Builder (конструктор правил)

```typescript
// frontend/src/pages/TraceabilityRules.tsx

interface TraceabilityRule {
  id?: number;
  name: string;
  description?: string;
  enabled: boolean;
  priority: number;

  sourceArtifactType: ArtifactType;
  targetArtifactType: ArtifactType;

  matchStrategy: MatchStrategy;
  matchConfig: Record<string, any>;

  sourceFilter?: Record<string, any>;
  targetFilter?: Record<string, any>;

  linkType: string;
  linkDirection: 'forward' | 'backward' | 'bidirectional';
  baseConfidence: number;
}

const TraceabilityRuleBuilder: React.FC = () => {
  const [rules, setRules] = useState<TraceabilityRule[]>([]);
  const [editingRule, setEditingRule] = useState<TraceabilityRule | null>(null);

  return (
    <Box>
      <Typography variant="h4">Traceability Rules</Typography>

      {/* Rule Templates */}
      <Paper sx={{ p: 2, mb: 2 }}>
        <Typography variant="h6">Quick Start Templates</Typography>
        <Stack direction="row" spacing={1}>
          <Button onClick={() => applyTemplate('commit_to_subtask_jira_key')}>
            Commit → Sub-task (JIRA key)
          </Button>
          <Button onClick={() => applyTemplate('subtask_to_user_story_parent')}>
            Sub-task → User Story (parent)
          </Button>
          <Button onClick={() => applyTemplate('confluence_to_user_story_title')}>
            Confluence → User Story (title)
          </Button>
        </Stack>
      </Paper>

      {/* Rules List */}
      <DataGrid
        rows={rules}
        columns={[
          { field: 'name', headerName: 'Rule Name', flex: 1 },
          { field: 'sourceArtifactType', headerName: 'Source', width: 120 },
          { field: 'targetArtifactType', headerName: 'Target', width: 120 },
          { field: 'matchStrategy', headerName: 'Strategy', width: 120 },
          { field: 'enabled', headerName: 'Enabled', type: 'boolean', width: 100 },
          { field: 'priority', headerName: 'Priority', width: 100 },
        ]}
        onRowClick={(params) => setEditingRule(params.row)}
      />

      {/* Rule Editor Dialog */}
      <Dialog open={!!editingRule} onClose={() => setEditingRule(null)}>
        <DialogTitle>
          {editingRule?.id ? 'Edit Rule' : 'Create Rule'}
        </DialogTitle>
        <DialogContent>
          <RuleEditorForm
            rule={editingRule}
            onSave={handleSaveRule}
          />
        </DialogContent>
      </Dialog>
    </Box>
  );
};

const RuleEditorForm: React.FC<{
  rule: TraceabilityRule | null;
  onSave: (rule: TraceabilityRule) => void;
}> = ({ rule, onSave }) => {
  return (
    <Box component="form">
      <TextField label="Rule Name" fullWidth required />
      <TextField label="Description" fullWidth multiline rows={2} />

      <Typography variant="subtitle1" sx={{ mt: 2 }}>Artifacts</Typography>
      <Grid container spacing={2}>
        <Grid item xs={6}>
          <FormControl fullWidth>
            <InputLabel>Source Type</InputLabel>
            <Select>
              <MenuItem value="Commit">Commit</MenuItem>
              <MenuItem value="JiraIssue">Jira Issue</MenuItem>
              <MenuItem value="ConfluencePage">Confluence Page</MenuItem>
              <MenuItem value="TestCase">Test Case</MenuItem>
            </Select>
          </FormControl>
        </Grid>
        <Grid item xs={6}>
          <FormControl fullWidth>
            <InputLabel>Target Type</InputLabel>
            <Select>
              <MenuItem value="JiraIssue">Jira Issue</MenuItem>
              <MenuItem value="ConfluencePage">Confluence Page</MenuItem>
              <MenuItem value="TestCase">Test Case</MenuItem>
            </Select>
          </FormControl>
        </Grid>
      </Grid>

      <Typography variant="subtitle1" sx={{ mt: 2 }}>Match Strategy</Typography>
      <FormControl fullWidth>
        <InputLabel>Strategy</InputLabel>
        <Select>
          <MenuItem value="jira_key">JIRA Key Pattern</MenuItem>
          <MenuItem value="regex">Custom Regex</MenuItem>
          <MenuItem value="title_match">Title Similarity</MenuItem>
          <MenuItem value="api_link">API Link Field</MenuItem>
        </Select>
      </FormControl>

      {/* Strategy-specific config */}
      <StrategyConfigEditor strategy={rule?.matchStrategy} />

      <Typography variant="subtitle1" sx={{ mt: 2 }}>Filters</Typography>
      <JsonEditor
        label="Source Filter (JSON)"
        placeholder='{"jira_issue_type": ["Sub-task"]}'
      />
      <JsonEditor
        label="Target Filter (JSON)"
        placeholder='{"jira_issue_type": ["User Story"]}'
      />

      <Grid container spacing={2} sx={{ mt: 2 }}>
        <Grid item xs={6}>
          <TextField label="Link Type" defaultValue="relates_to" fullWidth />
        </Grid>
        <Grid item xs={6}>
          <TextField
            label="Base Confidence"
            type="number"
            inputProps={{ min: 0, max: 100 }}
            defaultValue={80}
            fullWidth
          />
        </Grid>
      </Grid>
    </Box>
  );
};
```

### 5. API Endpoints

```python
# backend/app/api/api_v1/endpoints/traceability_rules.py

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.traceability.rule_engine import TraceabilityRuleEngine
from app.services.traceability.rule_templates import RULE_TEMPLATES

router = APIRouter()

@router.get("/rules")
async def list_rules(
    project_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db)
):
    """Список всех правил связывания."""
    query = select(TraceabilityRule)
    if project_id:
        query = query.where(
            (TraceabilityRule.project_id == project_id) |
            (TraceabilityRule.project_id.is_(None))
        )
    result = await db.execute(query)
    return result.scalars().all()

@router.get("/rules/templates")
async def list_templates():
    """Список шаблонов правил."""
    return RULE_TEMPLATES

@router.post("/rules")
async def create_rule(
    rule_data: TraceabilityRuleCreate,
    db: AsyncSession = Depends(get_db)
):
    """Создать новое правило."""
    rule = TraceabilityRule(**rule_data.dict())
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule

@router.post("/rules/{rule_id}/apply")
async def apply_rule(
    rule_id: int,
    project_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db)
):
    """Применить конкретное правило."""
    engine = TraceabilityRuleEngine(db)
    stats = await engine.apply_rules(
        project_id=project_id,
        rule_ids=[rule_id]
    )
    return stats

@router.post("/rules/apply-all")
async def apply_all_rules(
    project_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Применить все правила к проекту."""
    engine = TraceabilityRuleEngine(db)
    stats = await engine.apply_rules(project_id=project_id)
    return stats
```

## Пример использования (WaBank)

### Шаг 1: Создать правила через UI

```javascript
// Rule 1: Commit → Sub-task
{
  name: "WaBank: Commit → Sub-task",
  sourceArtifactType: "Commit",
  targetArtifactType: "JiraIssue",
  matchStrategy: "jira_key",
  matchConfig: {
    search_in: ["message", "branch_name"],
    pattern: "WAB-\\d+"
  },
  targetFilter: {
    jira_issue_type: ["Sub-task", "Task"]
  },
  linkType: "implements"
}

// Rule 2: Sub-task → User Story
{
  name: "WaBank: Sub-task → User Story (parent)",
  sourceArtifactType: "JiraIssue",
  targetArtifactType: "JiraIssue",
  matchStrategy: "api_link",
  matchConfig: {
    jira_field: "parent"
  },
  sourceFilter: {
    jira_issue_type: ["Sub-task"]
  },
  targetFilter: {
    jira_issue_type: ["Story", "User Story"]
  },
  linkType: "child_of"
}

// Rule 3: Confluence → User Story
{
  name: "WaBank: Confluence → User Story",
  sourceArtifactType: "ConfluencePage",
  targetArtifactType: "JiraIssue",
  matchStrategy: "jira_key",
  matchConfig: {
    search_in: ["title", "body"],
    pattern: "WAB-\\d+"
  },
  targetFilter: {
    jira_issue_type: ["Story", "User Story"]
  },
  linkType: "documents"
}
```

### Шаг 2: Запустить backfill

```bash
POST /api/v1/traceability/rules/apply-all?project_id=1
```

### Результат

```
Before:
  198 links (20% coverage)

After applying 3 rules:
  Commit → Sub-task: +650 links
  Sub-task → User Story: +150 links (transitive)
  Confluence → User Story: +45 links

Total: 1,043 links (95% coverage)
```

## Преимущества подхода

1. **Гибкость**: Каждая команда настраивает свои правила
2. **Прозрачность**: Видно какое правило создало связь
3. **Итеративность**: Можно тестировать правила на подвыборке
4. **Масштабируемость**: Новые стратегии = новые Python классы
5. **Confidence scoring**: Можно фильтровать ненадёжные связи

## Следующие шаги

1. Создать миграцию для таблицы `traceability_rules`
2. Реализовать базовые стратегии (jira_key, api_link)
3. UI для Rule Builder
4. Тестирование на WaBank данных
5. Добавить advanced стратегии (NLP, embeddings)

Что реализуем первым делом?
