"""
Traceability Rule Execution Engine

Интерпретирует React Flow JSON и выполняет правила трассировки.
"""
from typing import Dict, List, Any, Optional, Set
from datetime import datetime
from sqlalchemy.orm import Session
import re
import json

from app.models.traceability_rule import TraceabilityRule, TraceabilityRuleExecution
from app.models.traceability import Artifact, ArtifactLink


# ============================================================================
# SECURITY: Input Validation and Sanitization
# ============================================================================

class InputValidator:
    """Security validator for user inputs to prevent injection attacks."""

    # Whitelisted regex patterns (safe, commonly used patterns)
    SAFE_REGEX_PATTERNS = {
        'jira_key': r'\b[A-Z][A-Z0-9_]+-[0-9]+\b',
        'email': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        'url': r'https?://[^\s]+',
        'alphanumeric': r'[A-Za-z0-9]+',
        'word': r'\w+',
    }

    # Maximum regex complexity to prevent ReDoS
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

        # Remove null bytes and other control characters
        sanitized = value.replace('\x00', '').strip()

        return sanitized

    @staticmethod
    def validate_date(value: Any, field_name: str) -> datetime:
        """Validate date input."""
        if isinstance(value, datetime):
            return value

        if isinstance(value, str):
            try:
                # Try ISO 8601 format
                return datetime.fromisoformat(value.replace('Z', '+00:00'))
            except ValueError:
                raise ValueError(f"{field_name} must be a valid ISO 8601 date string")

        raise ValueError(f"{field_name} must be a datetime or ISO 8601 string")

    @staticmethod
    def validate_regex_pattern(pattern: str, allow_custom: bool = False) -> str:
        """
        Validate regex pattern to prevent ReDoS attacks.

        Args:
            pattern: The regex pattern to validate
            allow_custom: If False, only allow whitelisted patterns

        Raises:
            ValueError: If pattern is unsafe
        """
        if not isinstance(pattern, str):
            raise ValueError(f"Pattern must be a string, got {type(pattern).__name__}")

        # Check if pattern is in whitelist
        if not allow_custom:
            if pattern not in InputValidator.SAFE_REGEX_PATTERNS.values():
                # Check if it matches any safe pattern by name
                is_safe = False
                for safe_pattern in InputValidator.SAFE_REGEX_PATTERNS.values():
                    if pattern == safe_pattern:
                        is_safe = True
                        break

                if not is_safe:
                    raise ValueError(
                        f"Custom regex patterns are not allowed. Use one of: {', '.join(InputValidator.SAFE_REGEX_PATTERNS.keys())}"
                    )

        # Basic security checks
        if len(pattern) > InputValidator.MAX_REGEX_LENGTH:
            raise ValueError(f"Regex pattern too long (max {InputValidator.MAX_REGEX_LENGTH} chars)")

        # Check for dangerous patterns that can cause ReDoS
        # Nested quantifiers: (a+)+, (a*)*,  (a+)*, (a{1,5})+, etc.
        # Match patterns like: (...)+ or (...)* or (...){n,m} where ... contains quantifiers
        # Check for quantifiers inside parentheses followed by quantifiers after
        if re.search(r'\([^)]*[+*?{][^)]*\)[+*?{]', pattern):
            raise ValueError("Regex pattern contains nested quantifiers (potential ReDoS)")

        # Overlapping alternations with quantifiers: (a|a)*
        # This is a simplified check - more sophisticated analysis would be needed for production
        quantifier_count = len(re.findall(r'[+*?{]', pattern))
        if quantifier_count > InputValidator.MAX_REGEX_QUANTIFIERS:
            raise ValueError(f"Regex pattern has too many quantifiers (max {InputValidator.MAX_REGEX_QUANTIFIERS})")

        # Try to compile the pattern to ensure it's valid
        try:
            re.compile(pattern)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern: {str(e)}")

        return pattern

    @staticmethod
    def validate_list_of_strings(value: Any, field_name: str, max_items: int = 100, max_item_length: int = 500) -> List[str]:
        """Validate list of strings."""
        if isinstance(value, str):
            # Convert single string to list
            value = [value]

        if not isinstance(value, list):
            raise ValueError(f"{field_name} must be a list or string")

        if len(value) > max_items:
            raise ValueError(f"{field_name} exceeds maximum of {max_items} items")

        validated = []
        for item in value:
            validated.append(InputValidator.validate_string(item, f"{field_name} item", max_item_length))

        return validated


class ExecutionContext:
    """Контекст выполнения правила - хранит промежуточные данные между нодами."""

    def __init__(self, rule_id: int, db: Session, edges: List[Dict[str, Any]]):
        self.rule_id = rule_id
        self.db = db
        self.edges = edges
        self.node_outputs: Dict[str, List[Artifact]] = {}  # node_id -> artifacts
        self.links_created: List[ArtifactLink] = []
        self.errors: List[str] = []
        self.warnings: List[str] = []

        # Build edge lookup for fast access
        self.incoming_edges: Dict[str, List[Dict[str, Any]]] = {}
        for edge in edges:
            target = edge['target']
            if target not in self.incoming_edges:
                self.incoming_edges[target] = []
            self.incoming_edges[target].append(edge)

    def set_node_output(self, node_id: str, artifacts: List[Artifact]):
        """Сохранить результат выполнения ноды."""
        self.node_outputs[node_id] = artifacts

    def get_node_output(self, node_id: str) -> List[Artifact]:
        """Получить результат выполнения ноды."""
        return self.node_outputs.get(node_id, [])

    def add_link(self, link: ArtifactLink):
        """Добавить созданную связь."""
        self.links_created.append(link)

    def add_error(self, message: str):
        """Добавить ошибку."""
        self.errors.append(message)

    def add_warning(self, message: str):
        """Добавить предупреждение."""
        self.warnings.append(message)

    def get_input_artifacts(self, node_id: str) -> List[Artifact]:
        """Получить все входные артефакты для ноды."""
        all_inputs = []

        # Найти все входящие edges
        incoming = self.incoming_edges.get(node_id, [])

        for edge in incoming:
            source_id = edge['source']
            source_artifacts = self.node_outputs.get(source_id, [])
            all_inputs.extend(source_artifacts)

        return all_inputs


class NodeExecutor:
    """Базовый класс для выполнения нод."""

    def execute(self, node: Dict[str, Any], context: ExecutionContext) -> List[Artifact]:
        """Выполнить ноду и вернуть список артефактов."""
        raise NotImplementedError


class CommitSourceExecutor(NodeExecutor):
    """Выполнение Source Node: Git Commit."""

    def execute(self, node: Dict[str, Any], context: ExecutionContext) -> List[Artifact]:
        data = node.get('data', {})
        filters = data.get('filters', {})

        query = context.db.query(Artifact).filter(Artifact.type == 'commit')

        # SECURITY: Validate filter inputs before using in queries
        try:
            # Применяем фильтры
            if filters.get('branch'):
                branch = InputValidator.validate_string(filters['branch'], 'branch', max_length=500)
                query = query.filter(Artifact.metadata['branch'].astext == branch)

            if filters.get('author'):
                author = InputValidator.validate_string(filters['author'], 'author', max_length=500)
                query = query.filter(Artifact.metadata['author'].astext == author)

            if filters.get('date_from'):
                date_from = InputValidator.validate_date(filters['date_from'], 'date_from')
                query = query.filter(Artifact.created_at >= date_from)

            if filters.get('date_to'):
                date_to = InputValidator.validate_date(filters['date_to'], 'date_to')
                query = query.filter(Artifact.created_at <= date_to)
        except ValueError as e:
            context.add_error(f"Invalid filter in CommitSource: {str(e)}")
            return []

        artifacts = query.all()
        context.set_node_output(node['id'], artifacts)

        return artifacts


class JiraIssueSourceExecutor(NodeExecutor):
    """Выполнение Source Node: Jira Issue."""

    def execute(self, node: Dict[str, Any], context: ExecutionContext) -> List[Artifact]:
        data = node.get('data', {})
        filters = data.get('filters', {})

        query = context.db.query(Artifact).filter(Artifact.type == 'jira_issue')

        # SECURITY: Validate filter inputs before using in queries
        try:
            # Применяем фильтры
            if filters.get('project'):
                project = InputValidator.validate_string(filters['project'], 'project', max_length=200)
                query = query.filter(Artifact.metadata['project'].astext == project)

            if filters.get('issue_type'):
                issue_types = InputValidator.validate_list_of_strings(
                    filters['issue_type'],
                    'issue_type',
                    max_items=50,
                    max_item_length=200
                )
                query = query.filter(Artifact.metadata['issue_type'].astext.in_(issue_types))

            if filters.get('status'):
                statuses = InputValidator.validate_list_of_strings(
                    filters['status'],
                    'status',
                    max_items=50,
                    max_item_length=200
                )
                query = query.filter(Artifact.metadata['status'].astext.in_(statuses))
        except ValueError as e:
            context.add_error(f"Invalid filter in JiraIssueSource: {str(e)}")
            return []

        artifacts = query.all()
        context.set_node_output(node['id'], artifacts)

        return artifacts


class ConfluenceSourceExecutor(NodeExecutor):
    """Выполнение Source Node: Confluence Page."""

    def execute(self, node: Dict[str, Any], context: ExecutionContext) -> List[Artifact]:
        data = node.get('data', {})
        filters = data.get('filters', {})

        query = context.db.query(Artifact).filter(Artifact.type == 'confluence_page')

        # SECURITY: Validate filter inputs before using in queries
        try:
            # Применяем фильтры
            if filters.get('space'):
                space = InputValidator.validate_string(filters['space'], 'space', max_length=200)
                query = query.filter(Artifact.metadata['space'].astext == space)

            if filters.get('labels'):
                labels = InputValidator.validate_list_of_strings(
                    filters['labels'],
                    'labels',
                    max_items=50,
                    max_item_length=200
                )
                # PostgreSQL: jsonb @> operator, SQLite: нужна другая логика
                for label in labels:
                    query = query.filter(Artifact.metadata['labels'].astext.contains(label))
        except ValueError as e:
            context.add_error(f"Invalid filter in ConfluenceSource: {str(e)}")
            return []

        artifacts = query.all()
        context.set_node_output(node['id'], artifacts)

        return artifacts


class JiraKeyExtractorExecutor(NodeExecutor):
    """Выполнение Processor Node: Jira Key Extractor."""

    def execute(self, node: Dict[str, Any], context: ExecutionContext) -> List[Artifact]:
        data = node.get('data', {})
        config = data.get('config', {})

        # Получаем входные артефакты
        input_artifacts = context.get_input_artifacts(node['id'])

        # SECURITY: Validate regex pattern to prevent ReDoS attacks
        try:
            # Извлекаем Jira ключи
            search_in = config.get('search_in', ['message'])
            if not isinstance(search_in, list):
                search_in = [search_in]
            search_in = InputValidator.validate_list_of_strings(search_in, 'search_in', max_items=10, max_item_length=50)

            # Validate regex pattern (default is safe)
            pattern = config.get('pattern', r'\b[A-Z][A-Z0-9_]+-[0-9]+\b')
            # Allow custom patterns only if explicitly configured in settings
            allow_custom = getattr(context, 'allow_custom_regex', False)
            pattern = InputValidator.validate_regex_pattern(pattern, allow_custom=allow_custom)
        except ValueError as e:
            context.add_error(f"Invalid config in JiraKeyExtractor: {str(e)}")
            return []

        jira_keys = set()
        for artifact in input_artifacts:
            for field in search_in:
                text = self._get_field_value(artifact, field)
                if text:
                    try:
                        matches = re.findall(pattern, str(text))
                        jira_keys.update(matches)
                    except re.error as e:
                        context.add_error(f"Regex execution error in JiraKeyExtractor: {str(e)}")
                        continue

        # Найти соответствующие Jira issues
        if jira_keys:
            jira_artifacts = context.db.query(Artifact).filter(
                Artifact.type == 'jira_issue',
                Artifact.external_id.in_(jira_keys)
            ).all()
        else:
            jira_artifacts = []

        context.set_node_output(node['id'], jira_artifacts)
        return jira_artifacts

    def _get_field_value(self, artifact: Artifact, field: str) -> Optional[str]:
        """Получить значение поля из артефакта."""
        if field == 'message' and artifact.type == 'commit':
            return artifact.metadata.get('message')
        elif field == 'branch' and artifact.type == 'commit':
            return artifact.metadata.get('branch')
        elif field == 'title':
            return artifact.title
        elif field == 'description':
            return artifact.description
        return None


class FilterNodeExecutor(NodeExecutor):
    """Выполнение Processor Node: Filter."""

    # Whitelisted operators to prevent code injection
    ALLOWED_OPERATORS = {'equals', 'contains', 'not_equals', 'greater_than', 'less_than'}

    def execute(self, node: Dict[str, Any], context: ExecutionContext) -> List[Artifact]:
        data = node.get('data', {})
        config = data.get('config', {})

        input_artifacts = context.get_input_artifacts(node['id'])

        # SECURITY: Validate config inputs
        try:
            field = InputValidator.validate_string(config.get('field', ''), 'field', max_length=200)
            operator = InputValidator.validate_string(config.get('operator', ''), 'operator', max_length=50)

            # Validate operator is in whitelist
            if operator not in self.ALLOWED_OPERATORS:
                raise ValueError(f"Operator must be one of: {', '.join(self.ALLOWED_OPERATORS)}")

            # Validate value (can be string, number, or date)
            value = config.get('value')
            if isinstance(value, str):
                value = InputValidator.validate_string(value, 'value', max_length=1000)
        except ValueError as e:
            context.add_error(f"Invalid config in FilterNode: {str(e)}")
            return []

        filtered_artifacts = []
        for artifact in input_artifacts:
            field_value = self._get_field_value(artifact, field)

            if self._apply_operator(field_value, operator, value):
                filtered_artifacts.append(artifact)

        context.set_node_output(node['id'], filtered_artifacts)
        return filtered_artifacts

    def _get_field_value(self, artifact: Artifact, field: str) -> Any:
        return artifact.metadata.get(field)

    def _apply_operator(self, field_value: Any, operator: str, expected_value: Any) -> bool:
        if operator == 'equals':
            return field_value == expected_value
        elif operator == 'contains':
            return expected_value in str(field_value)
        elif operator == 'not_equals':
            return field_value != expected_value
        elif operator == 'greater_than':
            try:
                return float(field_value) > float(expected_value)
            except (TypeError, ValueError):
                return False
        elif operator == 'less_than':
            try:
                return float(field_value) < float(expected_value)
            except (TypeError, ValueError):
                return False
        return False


class DecisionNodeExecutor(NodeExecutor):
    """Выполнение Decision Node: условное ветвление."""

    def execute(self, node: Dict[str, Any], context: ExecutionContext) -> List[Artifact]:
        data = node.get('data', {})
        config = data.get('config', {})

        input_artifacts = context.get_input_artifacts(node['id'])

        condition_type = config.get('condition_type', 'count_threshold')
        threshold = config.get('threshold', 0)

        # Определить результат условия
        result = self._evaluate_condition(input_artifacts, condition_type, threshold)

        # Найти выходные edges с соответствующим handle ID
        outgoing_edges = [e for e in context.edges if e['source'] == node['id']]

        # Направить артефакты в соответствующий выход
        for edge in outgoing_edges:
            handle_id = edge.get('sourceHandle', 'true')

            if (result and handle_id == 'true') or (not result and handle_id == 'false'):
                # Эта ветка активна - артефакты пойдут дальше
                context.set_node_output(node['id'] + '_' + handle_id, input_artifacts)
            else:
                # Эта ветка неактивна - пустой список
                context.set_node_output(node['id'] + '_' + handle_id, [])

        # Для DecisionNode возвращаем все входные артефакты
        # Фактическое разделение происходит через edges
        context.set_node_output(node['id'], input_artifacts)
        return input_artifacts

    def _evaluate_condition(self, artifacts: List[Artifact], condition_type: str, threshold: Any) -> bool:
        """Вычислить условие."""
        if condition_type == 'count_threshold':
            return len(artifacts) >= int(threshold)
        elif condition_type == 'count_equals':
            return len(artifacts) == int(threshold)
        elif condition_type == 'has_artifacts':
            return len(artifacts) > 0
        elif condition_type == 'is_empty':
            return len(artifacts) == 0
        else:
            return True  # По умолчанию true


class CreateLinkActionExecutor(NodeExecutor):
    """Выполнение Action Node: Create Link."""

    def execute(self, node: Dict[str, Any], context: ExecutionContext) -> List[Artifact]:
        data = node.get('data', {})
        config = data.get('config', {})

        link_type = config.get('link_type', 'relates_to')
        bidirectional = config.get('bidirectional', False)

        # Получить входящие edges
        incoming = context.incoming_edges.get(node['id'], [])

        if len(incoming) < 1:
            context.add_error(f"CreateLinkAction node {node['id']} has no inputs")
            return []

        # Стратегия: если есть 2 входа, то source=первый, target=второй
        # Если 1 вход, то связываем все артефакты между собой (many-to-many)

        if len(incoming) == 1:
            # Self-linking: связываем артефакты из одного источника между собой
            artifacts = context.get_input_artifacts(node['id'])
            self._create_self_links(artifacts, link_type, bidirectional, context)

        elif len(incoming) == 2:
            # Cross-linking: связываем артефакты из двух источников
            source_edge = incoming[0]
            target_edge = incoming[1]

            source_artifacts = context.node_outputs.get(source_edge['source'], [])
            target_artifacts = context.node_outputs.get(target_edge['source'], [])

            self._create_cross_links(source_artifacts, target_artifacts, link_type, bidirectional, context)

        else:
            # Более 2 входов: связываем первый источник со всеми остальными
            source_edge = incoming[0]
            source_artifacts = context.node_outputs.get(source_edge['source'], [])

            for i in range(1, len(incoming)):
                target_artifacts = context.node_outputs.get(incoming[i]['source'], [])
                self._create_cross_links(source_artifacts, target_artifacts, link_type, bidirectional, context)

        return []

    def _create_self_links(self, artifacts: List[Artifact], link_type: str, bidirectional: bool, context: ExecutionContext):
        """Создать связи между артефактами из одного списка."""
        for i, source in enumerate(artifacts):
            for target in artifacts[i+1:]:
                self._create_link(source, target, link_type, context)
                if bidirectional:
                    reverse_type = self._get_reverse_link_type(link_type)
                    self._create_link(target, source, reverse_type, context)

    def _create_cross_links(self, sources: List[Artifact], targets: List[Artifact], link_type: str, bidirectional: bool, context: ExecutionContext):
        """Создать связи между двумя списками артефактов."""
        for source in sources:
            for target in targets:
                self._create_link(source, target, link_type, context)
                if bidirectional:
                    reverse_type = self._get_reverse_link_type(link_type)
                    self._create_link(target, source, reverse_type, context)

    def _create_link(self, source: Artifact, target: Artifact, link_type: str, context: ExecutionContext, base_confidence: float = 90.0):
        """Создать одну связь между артефактами."""
        # Проверить, существует ли уже такая связь
        existing = context.db.query(ArtifactLink).filter(
            ArtifactLink.source_artifact_id == source.id,
            ArtifactLink.target_artifact_id == target.id,
            ArtifactLink.link_type == link_type
        ).first()

        if existing:
            context.add_warning(f"Link already exists: {source.external_id} -> {target.external_id}")
            return

        # Вычислить confidence score
        confidence = self._calculate_confidence(source, target, link_type, base_confidence, context)

        # Создать новую связь
        link = ArtifactLink(
            source_artifact_id=source.id,
            target_artifact_id=target.id,
            link_type=link_type,
            confidence=confidence,
            created_by_rule_id=context.rule_id
        )

        context.db.add(link)
        context.add_link(link)

    def _calculate_confidence(self, source: Artifact, target: Artifact, link_type: str, base: float, context: ExecutionContext) -> float:
        """Вычислить confidence score на основе различных факторов."""
        confidence = base

        # Фактор 1: Тип связи (API links = 100%)
        if link_type in ['child_of', 'parent_of']:
            # Parent/child relationships from API are 100% confident
            confidence = 100.0

        # Фактор 2: Прямое совпадение external_id (высокая уверенность)
        if source.external_id and target.external_id:
            # Если Jira key найден в commit message напрямую
            if source.type == 'commit' and target.type == 'jira_issue':
                message = source.metadata.get('message', '')
                if target.external_id in message:
                    # Проверка позиции ключа в сообщении
                    if message.startswith(target.external_id):
                        confidence += 10  # Ключ в начале = +10%
                    confidence = min(100.0, confidence)

        # Фактор 3: Множественные ключи (снижение уверенности)
        if source.type == 'commit':
            message = source.metadata.get('message', '')
            jira_keys = re.findall(r'\b[A-Z][A-Z0-9_]+-[0-9]+\b', message)
            if len(jira_keys) > 1:
                confidence -= 5  # Несколько ключей = -5%

        # Фактор 4: Branch name match (повышение уверенности)
        if source.type == 'commit' and target.type == 'jira_issue':
            branch = source.metadata.get('branch', '')
            if target.external_id in branch:
                confidence += 5  # Ключ в ветке тоже = +5%

        # Ограничить диапазон 0-100
        return max(0.0, min(100.0, confidence))

    def _get_reverse_link_type(self, link_type: str) -> str:
        """Получить обратный тип связи."""
        reverse_map = {
            'implements': 'implemented_by',
            'tests': 'tested_by',
            'documents': 'documented_by',
            'child_of': 'parent_of',
            'depends_on': 'required_by',
            'blocks': 'blocked_by',
        }
        return reverse_map.get(link_type, f'reverse_{link_type}')


class RuleExecutionEngine:
    """Движок выполнения правил трассировки."""

    # Маппинг типов нод на исполнители
    EXECUTORS = {
        'commitSource': CommitSourceExecutor(),
        'jiraIssueSource': JiraIssueSourceExecutor(),
        'confluenceSource': ConfluenceSourceExecutor(),
        'jiraKeyExtractor': JiraKeyExtractorExecutor(),
        'filterNode': FilterNodeExecutor(),
        'decisionNode': DecisionNodeExecutor(),
        'createLinkAction': CreateLinkActionExecutor(),
    }

    def __init__(self, db: Session):
        self.db = db

    def execute_rule(self, rule_id: int) -> Dict[str, Any]:
        """Выполнить правило трассировки."""

        # Загрузить правило
        rule = self.db.query(TraceabilityRule).filter(TraceabilityRule.id == rule_id).first()
        if not rule:
            raise ValueError(f"Rule {rule_id} not found")

        if not rule.enabled:
            raise ValueError(f"Rule {rule_id} is disabled")

        # Парсить flow JSON
        flow_json = json.loads(rule.flow_json) if isinstance(rule.flow_json, str) else rule.flow_json
        nodes = flow_json.get('nodes', [])
        edges = flow_json.get('edges', [])

        # Создать контекст выполнения
        context = ExecutionContext(rule_id, self.db, edges)

        # Построить граф зависимостей
        execution_order = self._topological_sort(nodes, edges)

        # Выполнить ноды в правильном порядке
        for node_id in execution_order:
            node = next((n for n in nodes if n['id'] == node_id), None)
            if not node:
                context.add_error(f"Node {node_id} not found")
                continue

            node_type = node.get('type')
            executor = self.EXECUTORS.get(node_type)

            if not executor:
                context.add_error(f"No executor for node type: {node_type}")
                continue

            try:
                executor.execute(node, context)
            except Exception as e:
                context.add_error(f"Error executing node {node_id}: {str(e)}")

        # Сохранить результат выполнения
        execution = TraceabilityRuleExecution(
            rule_id=rule_id,
            status='success' if not context.errors else 'failed',
            links_created=len(context.links_created),
            execution_log={
                'errors': context.errors,
                'warnings': context.warnings,
                'links_created': len(context.links_created)
            },
            executed_at=datetime.utcnow()
        )
        self.db.add(execution)

        # Обновить статистику правила
        rule.total_executions += 1
        if not context.errors:
            rule.successful_executions += 1
        else:
            rule.failed_executions += 1
        rule.last_executed_at = datetime.utcnow()

        self.db.commit()

        return {
            'execution_id': execution.id,
            'status': execution.status,
            'links_created': len(context.links_created),
            'errors': context.errors,
            'warnings': context.warnings
        }

    def _topological_sort(self, nodes: List[Dict], edges: List[Dict]) -> List[str]:
        """Топологическая сортировка нод для определения порядка выполнения."""

        # Построить граф смежности
        graph = {node['id']: [] for node in nodes}
        in_degree = {node['id']: 0 for node in nodes}

        for edge in edges:
            source = edge['source']
            target = edge['target']
            graph[source].append(target)
            in_degree[target] += 1

        # Найти ноды без входящих рёбер (Source nodes)
        queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            current = queue.pop(0)
            result.append(current)

            for neighbor in graph[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # Проверка на циклы
        if len(result) != len(nodes):
            raise ValueError("Cycle detected in rule graph")

        return result
