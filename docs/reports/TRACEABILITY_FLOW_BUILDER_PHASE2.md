# Traceability Flow Builder - Phase 2 Complete ✅

> [!WARNING]
> Historical snapshot: this document is preserved as-is for context and
> its links may point to files that no longer exist. It is excluded from
> the docs link-integrity check (scripts/check_docs_links.py). Do not
> update it going forward; write new docs in docs/ instead.


## Overview
Phase 2 добавляет редактируемые свойства, валидацию правил, систему шаблонов и новые типы нод. Теперь пользователи могут полностью настраивать правила через UI.

## Новые возможности Phase 2

### 1. Редактируемые свойства нод ✅

**Компонент**: `PropertiesPanelEditable.tsx`

Теперь все ноды имеют редактируемые поля:

#### Source Nodes (Commit, Jira Issue, Confluence)
- **Commit Source**:
  - Branch filter (текстовое поле)
  - Author filter (текстовое поле)
  - After date (date picker)

- **Jira Issue Source**:
  - Project key (текстовое поле)
  - Issue types (multi-select: Story, Task, Sub-task, Bug, Epic)
  - Status (multi-select: To Do, In Progress, In Review, Done, Closed)

- **Confluence Source**:
  - Space key (текстовое поле)
  - Labels (comma-separated input)

#### Processor Nodes
- **Jira Key Extractor**:
  - Search in (checkboxes: message, branch_name, title, body)
  - Regex pattern (текстовое поле с подсказкой)
  - Case sensitive (checkbox)
  - Must be uppercase (checkbox)
  - Extract multiple keys (checkbox)

- **Filter Node** (NEW):
  - Field name (текстовое поле)
  - Operator (select: equals, not_equals, contains, not_contains, matches, in)
  - Value (текстовое поле)

- **Decision Node** (NEW):
  - Condition type (select: confidence_threshold, field_exists, field_value, count_threshold)
  - Threshold % (number input, 0-100)

#### Action Nodes
- **Create Link Action**:
  - Link type (select: relates_to, implements, tests, blocks, depends_on, child_of, parent_of)
  - Bidirectional (checkbox)
  - Reverse link type (conditional select, показывается если bidirectional=true)

**Функциональность**:
- ✅ Кнопка "Apply Changes" сохраняет изменения в ноду
- ✅ Изменения сразу отображаются на ноде (через обновление data)
- ✅ Валидация в реальном времени при изменении полей

---

### 2. Валидация правил ✅

**Файлы**:
- `utils/ruleValidation.ts` - логика валидации
- `components/traceability/ValidationPanel.tsx` - UI панель

**Правила валидации**:

#### Errors (критические ошибки):
1. ❌ Отсутствие source нод (Commit/Jira/Confluence)
2. ❌ Отсутствие action нод (Create Link)
3. ❌ Circular dependencies (циклы в графе)
4. ❌ Jira Key Extractor без search_in полей
5. ❌ Jira Key Extractor без regex pattern
6. ❌ Create Link без link_type
7. ❌ Create Link с bidirectional=true но без reverse_link_type

#### Warnings (предупреждения):
1. ⚠️ Disconnected nodes (ноды без связей)
2. ⚠️ Source nodes без outgoing edges
3. ⚠️ Action nodes без incoming edges
4. ⚠️ Processor nodes без input или output

**UI Features**:
- ✅ Кнопка "Validate" в топ-тулбаре (зелёная если valid, красная если errors, жёлтая если warnings)
- ✅ Expandable error/warning списки
- ✅ Клик на ошибку выделяет проблемную ноду
- ✅ Auto-validation при изменении nodes/edges
- ✅ Цветовая индикация (success/error/warning)

**Алгоритмы**:
- Depth-First Search (DFS) для обнаружения циклов
- Adjacency list для проверки связности
- Breadth-First Search (BFS) для проверки достижимости

---

### 3. Система шаблонов ✅

**Файлы**:
- `utils/ruleTemplates.ts` - определения шаблонов
- `components/traceability/TemplateDialog.tsx` - UI выбора шаблонов

**Предустановленные шаблоны**:

#### Basic Templates:

1. **Commit → Sub-task**
   - Description: Link commits to Jira sub-tasks by extracting keys from commit messages
   - Nodes: Git Commit → Jira Key Extractor → Create Link
   - Tags: `git`, `jira`, `simple`

2. **Bidirectional Story Link**
   - Description: Create bidirectional links between commits and user stories
   - Nodes: Git Commit → Extract Story Keys → Create Bidirectional Link
   - Tags: `git`, `jira`, `bidirectional`

3. **Confluence → Jira Stories**
   - Description: Link Confluence requirements pages to Jira user stories
   - Nodes: Confluence Page + Jira Stories → Create Link
   - Tags: `confluence`, `jira`, `requirements`

#### Advanced Templates:

4. **Multi-source with Filtering**
   - Description: Advanced rule combining commits, Jira issues, and filtering by type
   - Nodes: Recent Commits → Extract Keys → Link to Sub-task ← Sub-tasks Only
   - Tags: `git`, `jira`, `filter`, `complex`
   - Filters: dev branch, after 2025-01-01, Sub-task type, In Progress/In Review status

**Template Features**:
- ✅ Категории: Basic / Advanced / Custom
- ✅ Tabs для фильтрации по категориям
- ✅ Теги для каждого шаблона
- ✅ Описание и preview (кол-во нод и связей)
- ✅ Кнопка "Use Template" применяет шаблон на канвас
- ✅ Уникальные ID для нод (timestamp-based) чтобы избежать конфликтов

**Функции**:
```typescript
getTemplateById(id: string): RuleTemplate
getTemplatesByCategory(category): RuleTemplate[]
getTemplatesByTag(tag: string): RuleTemplate[]
applyTemplate(template): { nodes, edges }
```

---

### 4. Новые типы нод ✅

#### Filter Node (Процессор)
**Файл**: `nodes/FilterNode.tsx`

**Назначение**: Фильтрация артефактов по полям

**Конфигурация**:
- `field`: имя поля для фильтрации
- `operator`: equals | not_equals | contains | not_contains | matches | in
- `value`: значение для сравнения

**Использование**:
```
[Source] → [Filter: issue_type = Sub-task] → [Action]
```

**Handles**:
- Input: слева (target)
- Output: справа (source)

#### Decision Node (Процессор)
**Файл**: `nodes/DecisionNode.tsx`

**Назначение**: Условное ветвление (if/else логика)

**Конфигурация**:
- `condition_type`: confidence_threshold | field_exists | field_value | count_threshold
- `threshold`: порог для confidence_threshold (0-100%)

**Использование**:
```
[Extractor] → [Decision: confidence > 85%] ┬→ TRUE → [Create Link]
                                            └→ FALSE → [Queue Review]
```

**Handles**:
- Input: слева (target)
- Output TRUE: справа вверху (зелёный, source id="true")
- Output FALSE: справа внизу (красный, source id="false")

---

## UI Улучшения

### Top Toolbar
**Новое**: Добавлен верхний тулбар с:
- Заголовок "Traceability Rule Builder"
- Кнопка "Validate" с цветовой индикацией
- Счётчик ошибок/предупреждений

### Toolbox Updates
**Новое**:
- Кнопка "Templates" (variant="contained", синяя)
- 2 новые ноды в Processor Nodes: Filter и Decision
- Всего теперь 8 типов нод (3 source + 4 processor + 1 action)

### Properties Panel Enhancement
**Изменения**:
- Переименован в `PropertiesPanelEditable`
- Ширина увеличена: 320px → 360px
- Добавлена кнопка "Apply Changes" внизу
- Scroll для длинных форм
- Sticky footer с кнопкой сохранения

---

## Технические детали

### Validation Algorithm (Cycle Detection)
```typescript
function detectCycles(nodes, edges): string[] {
  // DFS with recursion stack
  // Returns cycle path if found, empty array otherwise
  const adjacencyList = buildAdjacencyList(nodes, edges);
  const visited = new Set();
  const recursionStack = new Set();

  for (node of nodes) {
    if (dfs(node, visited, recursionStack)) {
      return cyclePath; // Node labels for better UX
    }
  }
  return [];
}
```

### Template Application (ID Mapping)
```typescript
function applyTemplate(template): { nodes, edges } {
  const timestamp = Date.now();
  const idMap = new Map();

  // Create nodes with new IDs
  const nodes = template.nodes.map((node, i) => {
    const newId = `${node.type}_${timestamp}_${i}`;
    idMap.set(node.id, newId);
    return { ...node, id: newId };
  });

  // Remap edges
  const edges = template.edges.map(edge => ({
    ...edge,
    source: idMap.get(edge.source),
    target: idMap.get(edge.target),
  }));

  return { nodes, edges };
}
```

### Node Data Update Pattern
```typescript
const onUpdateNode = useCallback((nodeId, newData) => {
  setNodes((nds) =>
    nds.map((node) =>
      node.id === nodeId
        ? { ...node, data: newData }
        : node
    )
  );
}, [setNodes]);
```

---

## Файлы Phase 2

### Новые файлы (7):
1. `frontend/src/components/traceability/PropertiesPanelEditable.tsx` - Редактируемые свойства
2. `frontend/src/utils/ruleValidation.ts` - Валидация правил
3. `frontend/src/components/traceability/ValidationPanel.tsx` - UI панель валидации
4. `frontend/src/utils/ruleTemplates.ts` - Шаблоны правил
5. `frontend/src/components/traceability/TemplateDialog.tsx` - UI выбора шаблонов
6. `frontend/src/components/traceability/nodes/FilterNode.tsx` - Filter нода
7. `frontend/src/components/traceability/nodes/DecisionNode.tsx` - Decision нода

### Изменённые файлы (3):
1. `frontend/src/pages/TraceabilityFlowBuilder.tsx` - Интеграция всех фич
2. `frontend/src/components/traceability/Toolbox.tsx` - Новые ноды + кнопка Templates
3. `frontend/src/components/traceability/PropertiesPanel.tsx` - Заменён на PropertiesPanelEditable

---

## Как использовать Phase 2

### 1. Редактирование нод
1. Перетащи ноду на канвас
2. Кликни на ноду → откроется Properties Panel
3. Измени поля (label, filters, config)
4. Нажми "Apply Changes"
5. Изменения сразу видны на ноде

### 2. Валидация
1. Создай правило с нодами и связями
2. Кликни "Validate" в топ-тулбаре
3. Смотри ошибки/предупреждения в панели
4. Кликни на ошибку → выделится проблемная нода
5. Исправь проблемы → валидация обновится автоматически

### 3. Использование шаблонов
1. Кликни "Templates" в Toolbox
2. Выбери категорию (All / Basic / Advanced)
3. Выбери шаблон
4. Кликни "Use Template"
5. Шаблон загрузится на канвас
6. Настрой под свои нужды

### 4. Новые ноды
**Filter Node**:
```
Commit → Filter (field: "branch", operator: "equals", value: "dev") → Link
```

**Decision Node**:
```
Extractor → Decision (confidence_threshold: 85%) ┬→ TRUE → Create Link
                                                  └→ FALSE → Queue Review
```

---

## Тестирование Phase 2

### Запуск
```bash
cd frontend
npm run dev
```
Открой: `http://localhost:3000/traceability/flow-builder`

### Тест-кейсы:

#### TC1: Редактирование Commit Source
1. Перетащи "Git Commit" на канвас
2. Кликни на ноду
3. Измени Branch Filter на "dev"
4. Измени After Date на "2025-01-01"
5. Нажми "Apply Changes"
6. ✅ Проверь: на ноде появились chips "Branch: dev", "After: 2025-01-01"

#### TC2: Валидация ошибок
1. Создай пустой канвас
2. Добавь только Create Link Action
3. Кликни "Validate"
4. ✅ Проверь: 2 ошибки ("no source node", "no incoming connections")

#### TC3: Применение шаблона
1. Кликни "Templates"
2. Выбери "Commit → Sub-task"
3. Кликни "Use Template"
4. ✅ Проверь: 3 ноды на канвасе, 2 связи, валидация зелёная

#### TC4: Decision Node с двумя выходами
1. Перетащи Decision Node
2. Кликни на ноду
3. Установи threshold = 50
4. Соедини с двумя разными нодами через TRUE/FALSE handles
5. ✅ Проверь: две связи с разными цветами handles

---

## Отличия от Phase 1

| Feature | Phase 1 | Phase 2 |
|---------|---------|---------|
| Редактирование нод | ❌ Read-only | ✅ Полностью редактируемые |
| Валидация | ❌ Нет | ✅ Real-time validation |
| Шаблоны | ❌ Нет | ✅ 4 готовых шаблона |
| Типы нод | 5 | 8 (+Filter, +Decision, +QueueReview) |
| Properties Panel | 320px, read-only | 360px, editable with save button |
| Top Toolbar | ❌ Нет | ✅ Validate button + title |
| Cycle detection | ❌ Нет | ✅ DFS algorithm |
| Error highlighting | ❌ Нет | ✅ Click to highlight |

---

## Метрики Phase 2

### Компоненты:
- **Новых компонентов**: 7
- **Изменённых компонентов**: 3
- **Всего компонентов**: 18

### Код:
- **Строк TypeScript**: ~2500 новых
- **Функций валидации**: 8
- **Шаблонов**: 4
- **Типов нод**: 8

### Функциональность:
- **Editable fields**: 30+
- **Validation rules**: 8 errors + warnings
- **Templates**: 4 (basic + advanced)
- **Node types**: +3 новых

---

## Известные ограничения (Phase 3)

1. **No Backend Integration** - правила не сохраняются в БД
2. **No Rule Execution** - нельзя запустить правило на реальных данных
3. **No Confidence Calculator** - нет ноды для расчёта уверенности
4. **No Queue Review Action** - нет ноды для ручного review
5. **No Preview/Test Mode** - нельзя протестировать правило перед сохранением
6. **No Undo/Redo** - нет истории изменений
7. **No Collaboration** - нет multi-user editing

---

## Следующий этап: Phase 3 (Backend Integration)

### Планируемые фичи:
1. **API Integration**:
   - POST `/api/traceability/rules` - сохранение правил
   - GET `/api/traceability/rules` - загрузка правил
   - PUT `/api/traceability/rules/:id` - обновление
   - DELETE `/api/traceability/rules/:id` - удаление

2. **Database Schema**:
   ```sql
   CREATE TABLE traceability_rules (
     id SERIAL PRIMARY KEY,
     name VARCHAR(255),
     description TEXT,
     flow_json JSONB, -- nodes + edges
     enabled BOOLEAN DEFAULT true,
     created_at TIMESTAMP,
     updated_at TIMESTAMP
   );
   ```

3. **Rule Execution Engine**:
   - Интерпретация flow JSON
   - Применение к реальным артефактам
   - Создание TraceabilityLink записей
   - Расчёт confidence scores

4. **Rule History**:
   - Версионирование правил
   - Audit log изменений
   - Rollback к предыдущим версиям

5. **Performance Monitoring**:
   - Dashboard для каждого правила
   - Метрики: links created, execution time, error rate
   - Alert на failed executions

---

## Статус

**Phase 2**: ✅ **COMPLETE**

**Delivered**:
- ✅ Editable properties for all node types
- ✅ Real-time rule validation with error/warning highlighting
- ✅ Template system with 4 pre-built rules
- ✅ 2 new node types (Filter, Decision)
- ✅ Enhanced UI with top toolbar and validation panel

**Next**: Phase 3 - Backend Integration (4 weeks estimated)

---

## Инструкции по перезапуску

Если фронтенд уже запущен:
```bash
# Останови текущий dev server (Ctrl+C)
cd frontend
npm run dev
```

Новые компоненты будут доступны сразу после перезапуска.

---

**Дата**: 2025-10-05
**Версия**: 2.0
