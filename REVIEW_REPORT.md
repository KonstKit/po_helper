# PO Helper — Единый отчёт о необходимых правках

**Дата:** 2026-04-12
**Среда:** Docker (nginx:3001 → backend:8000, PostgreSQL, Redis)
**Проект:** WaBank (WAB), 645 задач, 58 участников

---

## 1. КРИТИЧЕСКИЕ БАГИ (блокируют работу пользователей)

### 1.1 PATCH `/projects/{id}` → 500 Internal Server Error

**Файл:** `backend/app/api/api_v1/endpoints/projects.py:264-285`

```
sqlalchemy.exc.InvalidRequestError: A transaction is already begun on this Session.
```

`ensure_project_access()` (строка 264) выполняет DB-запрос в implicit transaction, затем `async with db.begin()` (строка 285) пытается начать вторую транзакцию в той же сессии.

**Воспроизведение:**
```bash
curl -X PATCH "/api/v1/projects/1" -d '{"description":"test"}'  →  500
```

**Последствие:** редактирование проекта через UI невозможно — кнопка Save всегда падает.

**Исправление:** убрать `async with db.begin():` и работать напрямую с сессией + `await db.commit()`, либо использовать `db.begin_nested()`.

---

### 1.2 Alembic migrations не могут быть применены

**Причина:** таблица `alembic_version` вообще не существует в текущей БД (схема управляется вне Alembic). При попытке `alembic upgrade head` — создаётся таблица с `version_num varchar(32)`, а revision ID начиная с миграции 019 превышают 32 символа (`019_add_capacity_health_cfd_tables` = 38 символов), что вызывает `StringDataRightTruncationError`.

**Контекст:** колонка `execute_on_sync_complete` в live DB уже присутствует (добавлена вручную или другим путём). Проблема не в отсутствии конкретной колонки, а в том, что Alembic как инструмент миграций сломан и не может применить ни одну будущую миграцию.

**Исправление:** при инициализации Alembic расширить тип колонки:
```sql
ALTER TABLE alembic_version ALTER COLUMN version_num TYPE varchar(128);
```
И привести `alembic_version` в согласованное состояние с текущей схемой через `alembic stamp head`.

---

### 1.3 FilterNode не видит основные поля артефакта

**Файл:** `backend/app/services/traceability/engine/nodes/filter_node.py:48-50`

```python
def _get_field_value(self, artifact: Artifact, field: str) -> Any:
    meta = artifact.meta or {}
    return meta.get(field)  # ← ищет ТОЛЬКО в meta JSON
```

Поля `status`, `type`, `source`, `title` — колонки модели Artifact, не ключи в `meta`. Фильтр `status == "Done"` всегда возвращает пустой результат (0 связей) без каких-либо ошибок.

**Воспроизведение:** создано правило с filter `status equals Done` → execute → `artifacts_processed: 645, links_created: 0`. Создано правило с filter `task_type equals Communicating` (поле из meta) → execute → `links_created: 171`. Разница подтверждает, что filter ищет только в meta.

**Последствие:** Flow Builder выглядит рабочим, но правила с фильтром по основным атрибутам (status, type) молча ничего не делают.

**Исправление:**
```python
def _get_field_value(self, artifact: Artifact, field: str) -> Any:
    if hasattr(artifact, field):
        return getattr(artifact, field)
    meta = artifact.meta or {}
    return meta.get(field)
```

---

### 1.4 Nginx 307 redirect теряет порт

При обращении к endpoint без trailing slash FastAPI отдаёт 307 с `location: http://localhost/api/v1/...` (порт 80 вместо 3001). Внутри Docker-сети (nginx → backend на порту 80) это прозрачно, но при доступе с хоста через маппированный порт 3001 — redirect ведёт на несуществующий `localhost:80`.

**Воспроизведение:**
```bash
curl -v http://localhost:3001/api/v1/traceability/matrix?project_id=1
# → 307 → location: http://localhost/api/v1/traceability/matrix → connection refused
```

**Контекст:** фронтенд (axios) работает внутри Docker-сети через nginx на порту 80, поэтому в production это не проявляется. Баг актуален только при прямом доступе к API с хоста разработчика.

**Исправление (вариант A — nginx):**
```nginx
proxy_set_header Host $host:$server_port;
```

**Исправление (вариант B — FastAPI):**
```python
app = FastAPI(redirect_slashes=False)
```

---

## 2. ФУНКЦИОНАЛЬНЫЕ БАГИ (неправильная логика)

### 2.1 board_id фильтр в спринтах игнорируется

**Endpoint:** `GET /analytics/projects/{id}/sprints?board_id=99999`

**Воспроизведение:**
```
board_id=99999 (несуществующий) → total: 10 спринтов (все)
board_id=3057 (Kanban)          → total: 10 спринтов (те же самые)
board_id=3058 (Scrum)           → total: 10 спринтов (те же самые)
```

Фильтрация не реализована — SQL-запрос не содержит `WHERE board_id`.

---

### 2.2 Sprint velocity/commitment/completed всегда null

**Воспроизведение:**
```
GET /analytics/projects/1/sprints → все 10 спринтов: velocity=null, commitment=null, completed=null
GET /analytics/projects/1/velocity → average_velocity=391.0, sprint_velocities: Sprint 23=162, Sprint 22=435...
```

Velocity рассчитывается динамически в отдельном endpoint, но не записывается в Sprint-запись при sync. UI-вкладка Sprints на `/projects/1` показывает пустые карточки метрик для каждого спринта.

---

### 2.3 Coverage Analytics возвращает total_artifacts: 0

**Воспроизведение:**
```
GET /traceability/coverage-analytics?project_id=1 → total_artifacts: 0
GET /traceability/matrix?project_id=1             → total: 645
```

Два endpoint-а используют разные сервисы для подсчёта артефактов — один находит 645, другой 0.

---

### 2.4 Self-linking при одном input: O(n^2) связей

**Файл:** `backend/app/services/traceability/engine/nodes/create_link_action.py:43-47`

Когда в `CreateLinkAction` приходит один входящий поток (один edge), вызывается `_create_self_links()` — каждый артефакт линкуется с каждым в том же наборе: n*(n-1)/2 связей.

**Воспроизведение:** правило с фильтром по `task_type == "Communicating"` (19 артефактов) → 171 связь (19*18/2). Для 100 артефактов будет 4950, для 645 — 207690.

Это не ошибка в строгом смысле (поведение задокументировано в коде), но опасная семантика: пользователь ожидает cross-link между двумя потоками, а получает all-pairs внутри одного.

---

### 2.5 Usage Analytics — полная заглушка

**Воспроизведение:**
```
GET /usage-analytics/metrics/onboarding → {"detail": "Usage analytics is not implemented yet"}
GET /usage-analytics/metrics/summary    → {"detail": "Usage analytics is not implemented yet"}
```

Все 6 endpoint-ов (`/track`, `/track/batch`, `/metrics/onboarding`, `/metrics/time-to-value`, `/metrics/feature-adoption`, `/metrics/summary`) зарегистрированы в router, но возвращают stub.

---

## 3. АРХИТЕКТУРНЫЕ ЗАМЕЧАНИЯ (Traceability)

### 3.1 Auto-linking: suggestions генерируются автоматически, но approve только вручную

**Текущее состояние (подтверждено по коду):**

Автоматическая генерация suggestions через `post_sync.py:12` **реализована**: после Jira sync, если `artifact_delta > 0`, вызывается `_generate_suggestions_async()` / `generate_suggestions_task.delay()`. То же самое для Confluence sync (`confluence_tasks.py:594`) и Git import (`git_import_service.py:194`).

**Что остаётся проблемой:** каждый suggestion по-прежнему требует ручного approve/reject через UI. Для проектов с сотнями артефактов это создаёт bottleneck — suggestions копятся, но никто не просматривает их регулярно.

**Рекомендация:** добавить threshold-based auto-approve (например `confidence >= 0.95 → auto-approve`) или bulk-approve в UI с фильтром по confidence.

---

### 3.2 Нестабильный API-контракт: normalizeConfidenceDistribution

**Текущее состояние (подтверждено по коду):**

Нормализаторы `normalizeSyncHealth` и `normalizeDetailedSyncHealth` **удалены** — контракт sync-health стабилизирован. Остаётся один нормализатор:

**Файл:** `frontend/src/services/api/traceability.ts:61`

`normalizeConfidenceDistribution()` обрабатывает fallback `avg_confidence` → `avg`, пересчитывает median/min/max из histogram если отсутствуют в ответе.

**Рекомендация:** зафиксировать формат ответа confidence-distribution через Pydantic `response_model` на бэкенде — тогда фронтенд-нормализатор можно удалить.

---

## 4. НАБЛЮДЕНИЯ (не дефекты реализации)

Следующие разделы возвращают пустые данные не из-за багов, а из-за отсутствия настроенных интеграций. Это продуктово-операционный контекст, а не дефекты кода:

| Раздел | Статус API | Причина пустоты |
|--------|:---:|-----------------|
| Quality Metrics / Defects | 200 `[]` | Нет источника quality-метрик |
| Quality History | 200 `{total:0}` | Git не подключён → нет PR-ов |
| Testing Results / Runs | 200 `{data:[]}` | TestRail не подключён |
| Capacity Settings / CFD | 200 `{data:[]}` | Не настроены для команды |
| Confluence Pages | 200 `{count:0}` | Страницы не импортированы для проекта |
| Repositories | 200 `[]` | GitHub/GitLab не настроены |
| DORA Metrics | 200 | Git не подключён (0 deployments) |
| Value Metrics | 200 | `value_delivered: 0, ROI: 0` — не заполнено в данных |

---

## 5. БЕЗОПАСНОСТЬ

### 5.1 ~301 место с bare `except Exception`

Множество мест с широким перехватом исключений. Наиболее критичные:
- `core/crypto.py:72,92` — `except Exception: pass` молча проглатывает ошибки дешифрования
- `core/middleware.py:163` — исключения в middleware не логируются перед re-raise

**Рекомендация:** заменить на конкретные типы исключений, убрать `pass`-блоки в crypto.

---

## 6. ПЛАН ИСПРАВЛЕНИЙ ПО ПРИОРИТЕТУ

### Приоритет 1 — Критические (блокируют работу)
| # | Задача | Файл | Сложность |
|---|--------|------|-----------|
| 1 | Исправить PATCH `/projects/{id}` (двойная транзакция) | `projects.py:285` | Низкая |
| 2 | Привести Alembic в рабочее состояние (varchar(128) + stamp head) | SQL + alembic | Низкая |
| 3 | Исправить FilterNode: искать поля в модели, не только meta | `filter_node.py:48-50` | Низкая |

### Приоритет 2 — Важные (неправильная логика)
| # | Задача | Сложность |
|---|--------|-----------|
| 4 | Реализовать board_id фильтрацию спринтов | Низкая |
| 5 | Рассчитывать velocity/commitment при sync и сохранять в Sprint | Средняя |
| 6 | Исправить Coverage Analytics (total_artifacts: 0 vs 645) | Низкая |
| 7 | Добавить warning/guard при self-linking одного потока в CreateLinkAction | Низкая |
| 8 | Исправить Nginx redirect (потеря порта при dev-доступе) | Низкая |

### Приоритет 3 — Рекомендации
| # | Задача | Сложность |
|---|--------|-----------|
| 9 | Threshold-based auto-approve для suggestions (confidence >= 0.95) | Низкая |
| 10 | Стабилизировать API-контракт confidence-distribution (убрать normalizer) | Низкая |
| 11 | Убрать Usage Analytics stub endpoints или реализовать | Низкая |
| 12 | Заменить bare `except Exception` на конкретные исключения (crypto.py, middleware.py) | Средняя |
