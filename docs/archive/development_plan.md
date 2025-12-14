# PO Helper — Комплексный план развития для end‑to‑end трейсабилити

Этот документ фиксирует итоговую архитектуру, модель данных, API, интеграции, миграционную стратегию, наблюдаемость и дорожную карту для достижения сквозной трейсабилити: Требования → Задачи → Код → Тесты → Пайплайны → Деплой.

## Цели и KPI

- E2E‑трейсабилити: полноценная цепочка от Confluence требований до деплоя (Commits → PR/MR → Pipelines → Deployments → Tests).
- Покрытие связями ≥ 90% требований до тестов и деплоя.
- SLA синхронизаций: Git/CI ≤ 5 минут; Jira/Confluence/TestRail ≤ 15 минут.
- Quality Gates применяются к PR/MR и релизам (coverage, Sonar, security).
- Наблюдаемость: MTTR интеграционных инцидентов ≤ 30 минут; алерты по дрейфу связей.

## Текущее состояние (резюме)

- Backend: FastAPI + Python; SQLAlchemy ORM + Alembic; Celery + Redis.
- Интеграции: Jira (Basic/PAT), Confluence (поиск, страницы).
- Безопасность: JWT, bcrypt.
- База: PostgreSQL.
- Frontend: React + TS, MUI, Chart.js; Redux Toolkit + React Query; React Router.
- Функционал: синк проектов/задач из Jira, базовая velocity аналитика, спринт‑метрики, поиск/просмотр Confluence, управление пользователями/настройками.
- Ограничения: нет связей Confluence↔Jira, нет Git‑интеграции, нет QA/тестов, нет сквозной трейсабилити.

## Целевая архитектура

- Артефактный граф: единые таблицы `artifacts` (вершины) и `artifact_links` (рёбра) для всех сущностей: requirement, jira_issue, confluence_page, commit, pr/mr, pipeline, deployment, test_case, test_run и др.
- Коннекторы: плагины Jira, Confluence, GitHub/GitLab, TestRail, CI (GitHub Actions/Jenkins/GitLab CI).
- Оркестрация: Celery + Redis для синков, ретраев, дедупликации и бэкоффов. Опционально Streaming ETL (Kafka/Redpanda) для real‑time потоков.
- Кэш/представления: Redis + материализованные представления для матриц/потоков. Граф‑кэш (опционально Neo4j/Memgraph) для сложных path‑запросов.
- API: REST (FastAPI) + опционально GraphQL (федерация) для графовых запросов и объединения источников.
- Реал‑тайм: Webhook‑и от Git/CI/Jira/Confluence + WS/SSE обновления UI.
- Безопасность: KMS/Vault для секретов, RBAC, аудит действий, rate limiting, RLS для мульти‑тенантности.

## Модель данных

Унификация через `artifacts`/`artifact_links` с поддержкой версионирования и мульти‑тенантности.

### Таблицы (логическая схема)

1) artifacts

- id BIGSERIAL PK
- tenant_id UUID NOT NULL
- project_id BIGINT NOT NULL
- type TEXT NOT NULL              -- requirement|jira_issue|commit|pr|pipeline|deployment|test_case|test_run|confluence_page|...
- source TEXT NOT NULL            -- jira|confluence|github|gitlab|testrail|ci|internal
- external_id TEXT NOT NULL       -- ID в внешней системе (например, JIRA-123, SHA, pageId)
- display_key TEXT                -- человекочитаемый ключ (JIRA-123)
- title TEXT
- status TEXT
- url TEXT                        -- прямая ссылка на источник
- metadata JSONB                  -- произвольные поля
- version INT NOT NULL DEFAULT 1  -- версионирование артефактов
- parent_version_id BIGINT NULL   -- связь на предыдущую версию артефакта
- created_at TIMESTAMPTZ NOT NULL DEFAULT now()
- updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
- UNIQUE(tenant_id, project_id, type, source, external_id, version)

2) artifact_links

- id BIGSERIAL PK
- tenant_id UUID NOT NULL
- project_id BIGINT NOT NULL
- from_artifact_id BIGINT NOT NULL FK → artifacts(id)
- to_artifact_id BIGINT NOT NULL FK → artifacts(id)
- link_type TEXT NOT NULL          -- implements|tests|deploys|derives_from|relates_to|blocks|...
- confidence NUMERIC(3,2)          -- итоговый скор [0..1]
- confidence_factors JSONB         -- детальные факторы скоринга
- created_at TIMESTAMPTZ NOT NULL DEFAULT now()
- UNIQUE(tenant_id, project_id, from_artifact_id, to_artifact_id, link_type)

3) sources

- id BIGSERIAL PK
- tenant_id UUID NOT NULL
- project_id BIGINT NULL
- type TEXT NOT NULL               -- jira|confluence|github|gitlab|testrail|ci
- base_url TEXT
- auth JSONB                       -- хранить только зашифрованные секреты
- scopes TEXT[]
- settings JSONB
- created_at, updated_at

4) repositories

- id BIGSERIAL PK, tenant_id, project_id, provider (github|gitlab), repo_slug, default_branch, settings JSONB

5) sync_states

- id PK, tenant_id, source_id, project_id, last_cursor, last_event_id, etag, lag_seconds, rate_limit_reset_at, updated_at

6) legacy_mappings

- old_table TEXT, old_id BIGINT, new_artifact_id BIGINT, migrated_at TIMESTAMPTZ

7) audit_log

- id PK, tenant_id, actor_id, action TEXT, entity_type TEXT, entity_id BIGINT, payload JSONB, created_at

### Индексы и партиционирование

- Партиционирование `artifacts` по RANGE(created_at) (месячные) и опционально под‑партиции по tenant_id.
- Частичные индексы для «уверенных» связей:

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_links_confidence_high
ON artifact_links (from_artifact_id, to_artifact_id)
WHERE confidence >= 0.8;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_links_from_type_high
ON artifact_links (from_artifact_id, link_type, to_artifact_id)
WHERE confidence >= 0.8;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_links_to_type_high
ON artifact_links (to_artifact_id, link_type, from_artifact_id)
WHERE confidence >= 0.8;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_links_tests_high
ON artifact_links (from_artifact_id, to_artifact_id)
WHERE link_type='tests' AND confidence >= 0.8;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_links_tenant_project_high
ON artifact_links (tenant_id, project_id, from_artifact_id)
WHERE confidence >= 0.8;
```

- GIN индексы по JSONB (`artifacts.metadata`, `artifact_links.confidence_factors`).
- Покрывающие индексы: `(tenant_id, project_id, type)`, `(from_artifact_id, link_type)`, `(to_artifact_id, link_type)`.

### Версионирование и политика ссылок

- Версии артефактов образуют цепочку через `parent_version_id`.
- По умолчанию ссылки указывают на актуальную версию; для ретроспектив — сохраняем связь на конкретную версию.
- Допускается DAG‑ограничение для типов: `derives_from`, `implements`, `tests`, `deploys` (циклы только для `relates_to`).

### Мульти‑тенантность

- Везде `tenant_id` и включённая RLS с политикой `tenant_id = current_tenant()`.
- Все UNIQUE/FK ключи включают `tenant_id` (и при необходимости `project_id`) для корректной колокации.

## Миграционная стратегия (Alembic)

1) Добавить `artifacts`, `artifact_links`, `sources`, `sync_states`, `legacy_mappings`, `audit_log` без даунтайма.
2) Бэкфилл: спроецировать `User/Project/Task/Sprint/WorkLog/ConfluencePage` в `artifacts` (v1), заполнить `legacy_mappings`.
3) Двойная запись (старые таблицы + `artifacts`) под фиче‑флагом; валидация счётчиков и сэмплов.
4) Переключить API на чтение из новых таблиц; удалить двойную запись после стабилизации.
5) Создать материализованные представления для матрицы/потоков; настроить инкрементальные обновления Celery.

Откат: реверсивные миграции, снапшоты схемы,категорийные тесты на стенде.

## Интеграции

### Jira

- JQL курсоры по проекту, поддержка webhooks: issue, comment, transition.
- Smart‑commit ключи (`ABC-123`) из сообщений коммитов/PR.
- Нормализация статусов в enum для UI.

### Confluence

- Версионирование страниц, извлечение заголовков/якорей, поиск Jira‑ключей в тексте.
- Автосвязи Requirement → Jira Epic/Story по упоминаниям и структуре.

### GitHub/GitLab

- Webhooks: push, pull_request/merge_request, pipeline/check_suite, deployment; резервный polling.
- Парсинг commit/PR описаний для Jira ключей; автосоздание `commit→issue`, `pr→issue`.
- Метрики PR/MR: time‑to‑first‑review, cycle/lead time, rework, reviewers.
- Пайплайны: статусы, артефакты (JUnit/Coverage), длительности, flaky сигналы.
- Безопасность: PAT/OAuth в KMS/Vault; секреты — шифрованы (AES‑GCM или KMS‑envelope).

### Тестирование/QA

- TestRail: синк test cases со story/epic; автогенерация test runs; импорт результатов.
- Инжест JUnit/Allure из CI артефактов; маппинг `test_case_id`, связи к требованиям/задачам.
- Coverage/Sonar: импорт Jacoco/Cobertura; SonarQube measures (reliability/security/maintainability).
- Quality Gates: пороги; блокировка мерджа через GitHub Checks/GitLab Status.

## API

### Traceability

- GET /api/v1/traceability/requirement/{id}/flow — путь и статусы.
- GET /api/v1/traceability/task/{jira_key}/artifacts — связанные коммиты/PR/тесты/деплои.
- GET /api/v1/traceability/matrix?tenant_id=&project_id=&depth=&filters= — матрица и проценты покрытия.
- POST /api/v1/traceability/link — ручные связи (+ `confidence`/`confidence_factors`), аудит.

### Git

- GET /api/v1/git/repositories — список/состояния интеграций.
- POST /api/v1/git/sync/{repo_id} — форс‑синк.
- GET /api/v1/git/commits/{jira_key} — нормализованные коммиты по задаче.

### Testing

- GET /api/v1/testing/cases/{requirement_id}
- POST /api/v1/testing/results/sync — вебхук/ingest endpoint.
- GET /api/v1/testing/coverage/{feature_id}

### Health/Analytics/Incidents (новые)

- GET /api/v1/health/integrations/{source_id}/status — `last_sync_at`, `lag_seconds`, `last_error`, `rate_limit`, `webhook_delivery_ok`.
- POST /api/v1/artifacts/bulk-link — массовое создание/обновление связей (режимы `upsert`/`dry_run`, идемпотентность по `request_id`).
- GET /api/v1/analytics/velocity/prediction/{project_id} — прогноз velocity по историям спринтов.
- POST /api/v1/incidents/create-from-alert — из алерта создаёт инцидент и линкует артефакты.

### Graph (опционально)

- POST /api/v1/graph/query — декларативные запросы путей/срезов.

## Frontend (React + TS)

- Новые страницы: TraceabilityMatrix, RequirementFlow, CodeImpactAnalysis.
- Состояние: React Query селекторы под артефакты/связи; нормализованный кэш.
- UI‑паттерны: виртуализированные таблицы, DAG‑диаграмма, фильтры, подсветка разрывов.
- Реал‑тайм: WS/SSE обновления; индикаторы синка.
- UX: drill‑down, временная шкала, confidence‑факторы, экспорт CSV/PDF.

## Безопасность и соответствие

- RBAC: роли Admin/PO/Dev/QA/Viewer; гранулярные пермишены на проект/интеграцию.
- Секреты: KMS/Vault, шифрование секретов, ротация ключей.
- Аудит: `audit_log` для изменений связей/прав/интеграций.
- RLS: изоляция по `tenant_id`/`project_id`.
- Rate limiting: квоты на вебхуки/ингест, защита от штормов.

## Производительность и масштабирование

- Партиционирование: `artifacts` (месяц по `created_at`), автоматическое создание/присоединение партиций.
- Частичные индексы для высоких confidence, GIN по JSONB.
- CDC/Webhooks: event‑driven инжест; резервный polling.
- Граф‑кэш: лёгкий — Redis/материализованные представления; расширенный — Neo4j/Memgraph (синхронизация через CDC/Kafka Connect).
- Матрицы: инкрементальная пересборка Celery, TTL кэш.
- Горизонтальное шардирование: по `tenant_id` (например, Citus/Aurora PG), колокация таблиц.
- CQRS: primary для записи; read‑реплики для аналитики/отчётов.
- Time‑series метрики: отдельное хранение (TimescaleDB — простой старт; ClickHouse — при высоких объёмах/аналитике).

### Пример схемы метрик (TimescaleDB/ClickHouse)

TimescaleDB:

```sql
CREATE TABLE metrics_traceability (
  tenant_id uuid, project_id bigint, metric text,
  ts timestamptz NOT NULL, value double precision, labels jsonb,
  PRIMARY KEY (tenant_id, project_id, metric, ts)
);
SELECT create_hypertable('metrics_traceability', by_range('ts')); 
CREATE INDEX ON metrics_traceability (tenant_id, project_id, metric, ts DESC);
```

ClickHouse:

```sql
CREATE TABLE metrics_traceability (
  ts DateTime, tenant_id UUID, project_id Int64,
  metric LowCardinality(String), value Float64, labels JSON
) ENGINE=MergeTree PARTITION BY toYYYYMM(ts)
ORDER BY (tenant_id, project_id, metric, ts);
```

## Риски и меры

- Анти‑циклы в графе: перед вставкой ребра выполнять проверку наличия пути `to → from` (recursive CTE). При цикле — 409 Conflict; исключение — `relates_to`.
- Webhook флуд и force‑push: идемпотентность по delivery GUID, дедупликация/compaction (collapse), circuit breaker per `source_id`, деградация в polling‑режим, backpressure в очередях.
- Рейт‑лимиты API: экспоненциальный бэкофф, etag/if‑modified‑since, ночные бэкфиллы.
- Шумные автосвязи: порог `confidence`, ручное подтверждение «suggested links», аудит решений.
- Неполные CI‑данные: договор публикации артефактов (JUnit/coverage) в стабильные пути.
- Разнородные идентификаторы: `artifact_uid = (type, source, external_id, tenant_id, project_id)`; таблица `identities` при необходимости.
- Мультитенантность: строгие RLS, скопированные JWT‑клеймы, периметр для секретов per tenant.

## Observability

- Метрики:
  - traceability_coverage_percentage{tenant_id, project_id, artifact_type}
  - sync_lag_seconds{source, project_id}
  - auto_link_confidence_distribution{project_id}
  - broken_links_count{project_id, link_type}
  - webhook_qps{source}, webhook_dropped_total{reason}, circuit_open{source}
- Трейсинг: OpenTelemetry для API/воркеров; trace‑id пробрасывается через вебхуки/очереди.
- Логи: структурированные, корреляция по trace‑id, семплирование при высоких QPS.
- Алерты: SLO лагов синка, рост «сломанных» связей, деградация автосвязей, затяжные пайплайны, ошибки вебхуков.

### Операционные проверки качества

Еженедельный контроль деградации автосвязей и целостности матрицы:

```python
def link_quality_check(project_id: int, threshold_drop=0.15, broken_growth=0.2):
    """Еженедельная проверка деградации автосвязок"""
    # 1) Доля high-confidence связей за последние недели
    sql_ratio = """
      WITH w AS (
        SELECT date_trunc('week', created_at) wk,
               count(*) total,
               count(*) FILTER (WHERE confidence >= 0.8) hi
        FROM artifact_links
        WHERE project_id = :pid AND created_at >= now() - interval '21 days'
        GROUP BY 1
      )
      SELECT
        max(CASE WHEN wk = date_trunc('week', now()) - interval '1 week' THEN hi::float/NULLIF(total,0) END) cur,
        max(CASE WHEN wk = date_trunc('week', now()) - interval '2 weeks' THEN hi::float/NULLIF(total,0) END) prev
      FROM w;
    """
    cur, prev = db.fetch_one(sql_ratio, {'pid': project_id})
    drop = (prev or 0) - (cur or 0)

    # 2) Рост «сломанных» связей/разрывов
    sql_broken = """
      SELECT count(*) FROM traceability_gaps
      WHERE project_id=:pid AND detected_at >= now() - interval '14 days';
    """
    broken_now = db.fetch_val(sql_broken, {'pid': project_id})
    broken_prev = db.fetch_val(sql_broken.replace('14','28'), {'pid': project_id}) - broken_now

    if drop > threshold_drop or (broken_prev and (broken_now-broken_prev)/broken_prev > broken_growth):
        alert_if_degrading(project_id, drop, broken_now)
```

Источник `traceability_gaps`: инкрементальный отчёт (требования без `tests`/`deploys`, циклы, устаревшие связи).

## Confidence‑модель

- Факторы: `text_similarity`, `timeline_proximity`, `author_match`, `path_similarity`, `file_overlap`, `commit_message_match` и др.
- Агрегация: взвешенная формула (фиче‑флагом можно переключать на ML‑скоринг).
- Прозрачность: факторы хранятся в `confidence_factors`; итоговый `confidence` сравнивается с порогом для автолинка; ниже порога — «предложение» для ручного подтверждения (аудит).

## Альтернативные/дополнительные подходы (опционально)

- Event Sourcing: сохранение immutable событий (webhook/ingest) → реконструкция артефактов и аудит.
- GraphQL Federation: чтение «на лету» без полного синка из внешних источников.
- Streaming ETL: Kafka/Redpanda для webhooks/CDC; коннекторы в Neo4j/S3/warehouse.

## Дорожная карта

Этап 0.5 (2 недели): PoC Requirements → Tasks → Commits

- БД: минимальные `artifacts/links`; автолинк по Jira‑ключам.
- UI: простая матрица + flow для одного проекта.
- Критерий: ≤ 1 сек/запрос на ~1k артефактов.

Этап 1 (3–4 недели): Фундамент + Версионирование + Мульти‑тенантность

- Деливериблы: `artifacts/links/sources/sync_states`, бэкфилл, базовые Traceability API, матрица MVP, RLS, анти‑циклы.
- Критерии: ≥ 80% Jira Issues связаны с Confluence требованиями; матрица ≤ 3 сек на 10k артефактов.

Этап 2 (4–5 недель): Git + Circuit Breaker + Граф‑кэш (лёгкий)

- Деливериблы: webhooks, дедуп/compaction, PR/MR метрики, кэш путей в Redis.
- Критерии: ≥ 90% коммитов с Jira‑ключами автоматически линкуются; PR видит тест/пайплайн статус.

Этап 3 (3–4 недели): Тестирование + Quality Gates

- Деливериблы: TestRail/JUnit/coverage, блокировки PR/MR через статусы.
- Критерии: покрытие требований рассчитывается; нарушения гейтов блокируют мердж.

Этап 4 (2–3 недели): E2E Dashboard

- Деливериблы: RequirementFlow, интерактивная схема, real‑time статусы, drill‑down.

Этап 5 (4–5 недель): AI/Автосвязи

- Деливериблы: NLP сопоставление требований и задач, приоритизация по confidence, предложения связей.
- Критерии: точность автосвязей ≥ 0.8 F1 на пилотных данных.

Этап 6 (2–3 недели): Reporting/Compliance

- Деливериблы: аудит‑отчёты, шаблоны ISO/SOX, экспорт.

Этап 6.5 (3 недели): ML‑pipeline улучшения

- Деливериблы: feature store, retraining, A/B скоринг‑моделей.

Этап 7 (2 недели): Mobile/PWA

- Деливериблы: мобильные сценарии для стейкхолдеров (обзор статусов/рисков).

## Следующие шаги

- Утвердить DDL (versioning, tenant_id, confidence_factors), политики RLS и частичные индексы.
- Выбрать стратегию граф‑кэша: Redis сейчас, Neo4j позже (по необходимости).
- Определить целевые Git/CI и тест‑менеджмент для пилота.
- Запустить Этап 0.5 (PoC) на одном проекте под фиче‑флагами.
- Принять решение Timescale vs ClickHouse для метрик и подготовить инжест.

