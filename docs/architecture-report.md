# ПОДРОБНЫЙ АНАЛИЗ ПРИЛОЖЕНИЯ PO HELPER

## Дата анализа: 9 декабря 2025

---

## 1. ОБЩАЯ СТРУКТУРА ПРОЕКТА И ЕГО НАЗНАЧЕНИЕ

### 1.1 Описание приложения

**PO Helper** (Product Owner Helper) — это комплексный инструмент управления проектами для Product Owner-ов, работающих с Jira и Confluence. Приложение предоставляет интегрированное решение для:

- Синхронизации данных с Jira в реальном времени
- Аналитики командной производительности (velocity, burndown charts)
- Управления рисками проекта с автоматической диагностикой
- Прогнозирования сроков завершения проектов
- Отслеживания трассируемости артефактов (требования → задачи → тесты → коммиты)
- Интеграции с Confluence для связи документации и требований
- Управления качеством кода и техническим долгом

### 1.2 Архитектурный тип

**Тип**: Полнофункциональное веб-приложение (Full-Stack)
**Паттерн**: Clean Architecture с разделением на слои (API, Service, Repository)
**Масштабируемость**: От монолита к микросервисам (поддерживается асинхронная обработка через Celery)

### 1.3 Целевая аудитория

- Product Owner-ы
- Менеджеры проектов
- Аналитики качества
- DevOps инженеры
- Лидеры команд разработки

---

## 2. ОСНОВНЫЕ ТЕХНОЛОГИИ И ФРЕЙМВОРКИ

### 2.1 Backend стек

| Компонент | Технология | Версия | Назначение |
|-----------|-----------|--------|-----------|
| **Веб-фреймворк** | FastAPI | 0.109.0 | REST API, асинхронная обработка |
| **ASGI сервер** | Uvicorn | 0.27.0 | Запуск приложения |
| **ORM** | SQLAlchemy | 2.0.25 | Работа с БД, асинхронные запросы |
| **Миграции БД** | Alembic | 1.13.1 | Версионирование схемы БД |
| **Основная БД** | PostgreSQL | 15 | Хранилище данных проекта |
| **Кэширование** | Redis | 7 | Кэш и очередь сообщений |
| **Асинхронные задачи** | Celery | 5.3.6 | Фоновая обработка (Jira синхронизация) |
| **Драйвер БД** | asyncpg | 0.29.0 | Асинхронный доступ к PostgreSQL |
| **Интеграции** | atlassian-python-api | 3.41.4 | API Jira и Confluence |
| **HTTP клиент** | httpx, requests | 0.26.0, 2.31.0 | HTTP запросы с retry/timeout |
| **Валидация** | Pydantic | 2.5.3 | Валидация данных, сериализация |
| **Шифрование** | python-jose | 3.3.0 | JWT токены для аутентификации |
| **Хеширование паролей** | passlib/bcrypt | 1.7.4 | Безопасное хранение паролей |
| **Rate limiting** | slowapi | 0.1.7 | Ограничение частоты запросов |
| **Excel экспорт** | openpyxl, pandas | 3.1.2, 2.1.4 | Создание отчетов |
| **Мониторинг** | sentry-sdk | 1.40.6 | Отслеживание ошибок в production |
| **Тестирование** | pytest | 7.4.4 | Модульное и интеграционное тестирование |

### 2.2 Frontend стек

| Компонент | Технология | Версия | Назначение |
|-----------|-----------|--------|-----------|
| **UI фреймворк** | React | 18.2.0 | Создание интерфейса |
| **Язык** | TypeScript | 5.3.3 | Типизация JavaScript |
| **Сборка** | Vite | 5.2.0 | Быстрая разработка и production build |
| **Компоненты** | Material-UI (MUI) | 5.15.3 | Профессиональные UI компоненты |
| **Иконки** | @mui/icons-material | 5.15.3 | SVG иконки |
| **Таблицы** | @mui/x-data-grid | 6.18.7 | Продвинутые таблицы с сортировкой |
| **Стилизация** | @emotion/react,styled | 11.11.3 | CSS-in-JS для стилей |
| **State Management** | Redux Toolkit | 2.0.1 | Глобальное состояние приложения |
| **React hooks** | react-redux | 9.1.0 | Интеграция Redux с компонентами |
| **Server State** | @tanstack/react-query | 5.17.9 | Кэширование и синхронизация серверного состояния |
| **HTTP клиент** | axios | 1.6.5 | HTTP запросы к API |
| **Роутинг** | react-router-dom | 6.21.1 | Навигация между страницами |
| **Графики** | chart.js, recharts | 4.4.1, 2.10.4 | Визуализация данных |
| **Flow диаграммы** | reactflow | 11.11.4 | Interactive диаграммы (трассируемость) |
| **Формы** | react-hook-form | 7.48.2 | Управление формами с валидацией |
| **Дата/время** | date-fns | 3.2.0 | Работа с датами |
| **Тестирование** | vitest, @testing-library | 3.2.4, 14.1.2 | Unit тесты и интеграционные тесты |
| **E2E тестирование** | Puppeteer | 24.22.3 | Автоматизированное тестирование UI |

### 2.3 Infrastructure

| Компонент | Назначение |
|-----------|-----------|
| **Docker** | Контейнеризация приложения |
| **Docker Compose** | Оркестрация контейнеров при разработке |
| **Nginx** | Reverse proxy и раздача статических файлов |
| **PostgreSQL** | Основное хранилище данных |
| **Redis** | Кэш и очередь для Celery |
| **GitHub Actions** | CI/CD pipeline (упоминается в документации) |

---

## 3. АРХИТЕКТУРА ПРИЛОЖЕНИЯ

### 3.1 Общая диаграмма архитектуры

```
┌─────────────────────────────────────────────────────────────┐
│                    КЛИЕНТ (Frontend)                        │
│                                                              │
│  React + TypeScript + MUI                                   │
│  - Dashboard с KPI и чартами                               │
│  - Управление проектами и задачами                         │
│  - Трассируемость артефактов (Flow Builder)                │
│  - Аналитика и риски                                       │
│  - Настройки интеграций                                    │
└────────────┬────────────────────────────────────────────────┘
             │ HTTPS / REST API / WebSocket
┌────────────▼────────────────────────────────────────────────┐
│                  BACKEND (FastAPI)                          │
│  │                                                          │
│  ├─ API Layer (REST endpoints)                             │
│  │  ├─ /api/v1/projects/ (CRUD проектов)                 │
│  │  ├─ /api/v1/tasks/ (управление задачами)              │
│  │  ├─ /api/v1/analytics/ (analytics и метрики)          │
│  │  ├─ /api/v1/jira/ (синхронизация Jira)               │
│  │  ├─ /api/v1/traceability/ (трассируемость)           │
│  │  ├─ /api/v1/settings/ (конфигурация)                 │
│  │  └─ /api/v1/health/ (мониторинг и метрики)           │
│  │                                                         │
│  ├─ Service Layer (бизнес-логика)                         │
│  │  ├─ JiraService (синхронизация Jira)                 │
│  │  ├─ ConfluenceService (синхронизация Confluence)     │
│  │  ├─ AnalyticsService (расчет метрик)                 │
│  │  ├─ TraceabilityService (построение связей)          │
│  │  ├─ RuleExecutionEngine (выполнение правил)          │
│  │  └─ CacheService (кэширование)                        │
│  │                                                         │
│  ├─ Repository Layer (доступ к данным)                    │
│  │  └─ SQLAlchemy ORM + async запросы                    │
│  │                                                         │
│  └─ Core Layer (конфигурация, утилиты)                    │
│     ├─ Security (JWT, RBAC)                               │
│     ├─ Database (подключение, миграции)                   │
│     ├─ Crypto (шифрование credentials)                    │
│     ├─ Metrics (Prometheus метрики)                       │
│     └─ Middleware (CORS, logging, rate limiting)          │
│                                                             │
└──────┬──────────┬──────────┬──────────┬──────────────────────┘
       │          │          │          │
       ▼          ▼          ▼          ▼
    ┌────────────────────────────────────────┐
    │  Jira API  │ Confluence │ GitHub/GitLab│ Redis/Celery
    │  (atlassian-python-api)                │
    └────────────────────────────────────────┘
             │                  │
             ▼                  ▼
    ┌──────────────────────────────────┐
    │   PostgreSQL Database            │
    │                                  │
    │  Tables:                         │
    │  - users, roles                  │
    │  - projects, sprints, tasks      │
    │  - jira_syncs, issues            │
    │  - traceability_matrix           │
    │  - quality_metrics               │
    │  - settings (encrypted)          │
    │  - audit_logs                    │
    └──────────────────────────────────┘
```

### 3.2 Слоистая архитектура

**FastAPI приложение использует Clean Architecture с 4 основными слоями:**

#### Слой 1: API Layer (`/api/v1/endpoints`)
- REST endpoints для всех операций
- Валидация входящих данных (Pydantic schemas)
- Обработка ошибок и HTTP статусов
- Аутентификация и авторизация

#### Слой 2: Service Layer (`/services`)
- Основная бизнес-логика приложения
- Оркестрация между компонентами
- Сложные вычисления (аналитика, прогнозирование)
- Интеграции с внешними сервисами

#### Слой 3: Repository Layer (embedded в SQLAlchemy)
- Direct доступ к базе данных
- ORM запросы (асинхронные через asyncpg)
- Трансакции и консистентность данных

#### Слой 4: Core Layer (`/core`)
- Конфигурация (settings.py)
- Безопасность (security.py, crypto.py)
- Подключение к БД (database.py)
- Кэширование (cache.py)
- Middleware и интеграции

### 3.3 Ключевые архитектурные паттерны

| Паттерн | Реализация | Назначение |
|---------|-----------|-----------|
| **MVC** | Models + Controllers/Endpoints | Разделение данных и логики |
| **Service Layer** | Services folder | Бизнес-логика отдельно от контроллеров |
| **Repository** | SQLAlchemy ORM | Абстракция доступа к БД |
| **Dependency Injection** | FastAPI's `Depends()` | Инъекция зависимостей в endpoints |
| **Circuit Breaker** | JiraService с circuit breaker | Защита от cascading failures при Jira outages |
| **Observer/Pub-Sub** | Webhook handlers | Реакция на события из Git/Jira |
| **Factory** | Service factories (auth_strategy) | Создание правильного клиента auth |
| **Decorator** | @app.get, @app.post и т.д. | Маршрутизация endpoints |
| **Strategy** | Auth strategies (email vs PAT) | Выбор способа аутентификации в Jira |
| **Caching** | Redis + in-memory cache | Оптимизация производительности |

---

## 4. КЛЮЧЕВЫЕ КОМПОНЕНТЫ И МОДУЛИ

### 4.1 Backend компоненты

#### 4.1.1 Ядро интеграций (Jira)

**Файлы**: `backend/app/services/jira/`

```
jira/
├── auth_strategy.py        # Стратегия аутентификации (Email+Token vs PAT)
├── circuit_breaker.py      # Circuit breaker для защиты от cascading failures
├── http_client.py          # HTTP клиент с retry/timeout логикой
├── jira_service.py         # Основной сервис Jira
├── board_service.py        # Работа с Jira board
├── project_service.py      # Работа с проектами
├── response_handler.py      # Парсинг ответов Jira
└── version_resolver.py     # Определение версии Jira
```

**Ключевая особенность**: Circuit breaker паттерн предотвращает бесконечные retry циклы при недоступности Jira.

#### 4.1.2 Синхронизация (Sync Layer)

**Файлы**: `backend/app/services/sync/`

```
sync/
├── board_sync_service.py           # Синхронизация досок
├── issue_sync_service.py           # Синхронизация issues/задач
├── project_sync_orchestrator.py    # Оркестрация всей синхронизации
├── sprint_snapshot_service.py      # Снимки состояния спринтов
└── worklog_sync_service.py         # Синхронизация времени работы
```

#### 4.1.3 Аналитика

**Файлы**: `backend/app/services/` + `backend/app/api/api_v1/endpoints/analytics.py`

**Метрики**:
- Team Velocity (story points per sprint)
- Burndown charts (progress tracking)
- Completion rates
- Resource utilization
- Budget tracking
- Quality metrics (bug rates, code coverage)
- Risk indicators

#### 4.1.4 Трассируемость артефактов

**Файлы**: `backend/app/services/rule_execution_engine.py`, `backend/app/models/traceability.py`

**Возможности**:
- Связь Requirements → Tasks → Tests → Commits
- Правила построения связей (traceability rules)
- Confidence scoring (уверенность в связях)
- Backfill механизм для старых данных

#### 4.1.5 Безопасность & RBAC

**Файлы**: `backend/app/core/security.py`, `backend/app/models/rbac.py`

**Уровни доступа**:
- User (базовый пользователь)
- Manager (управление проектом)
- Admin (полный доступ)

**Механизмы**:
- JWT токены для аутентификации
- Шифрование чувствительных данных (credentials)
- Rate limiting (slowapi)

#### 4.1.6 Модели данных

**Основные таблицы PostgreSQL**:

| Модель | Описание |
|--------|----------|
| `User` | Пользователи системы с ролями |
| `Project` | Проекты, связанные с Jira |
| `Sprint` | Спринты проекта |
| `Task` | Задачи из Jira |
| `JiraFieldMapping` | Маппинг custom fields Jira |
| `IntegrationSetting` | Credentials для интеграций (encrypted) |
| `ConnectorConfig` | Проектные overrides/enablement для интеграций |
| `Source` | Рантайм-инстанс коннектора (base_url/auth/scopes) |
| `TraceabilityMatrix` | Матрица связей артефактов |
| `TraceabilityRule` | Правила для трассируемости |
| `QualityMetric` | Метрики качества кода |
| `AuditLog` | Лог всех действий пользователей |
| `GitRepository` | GitHub/GitLab репозитории |
| `TestCase` | Тестовые случаи (из TestRail) |

### 4.2 Frontend компоненты

#### 4.2.1 Страницы (Pages)

| Страница | Назначение | Модули |
|---------|-----------|--------|
| **Login** | Аутентификация | JWT auth, защита роутов |
| **Dashboard** | Главная страница | KPI, charts, alerts |
| **Projects** | Список проектов | CRUD, фильтрация |
| **ProjectDetail** | Детали проекта | Sprint info, задачи, история |
| **Tasks** | Управление задачами | Table, фильтры, bulk операции |
| **Analytics** | Аналитика и KPI | Velocity charts, burndown, прогнозы |
| **AnalyticsDashboard** | Полная аналитика | Комплексные метрики и отчеты |
| **Traceability** | Трассируемость | Matrix view, фильтры |
| **TraceabilityFlowBuilder** | Конструктор потоков | Visual flow editor (reactflow) |
| **Quality** | Метрики качества | Code coverage, bug rates |
| **Testing** | Управление тестами | TestRail integration |
| **Knowledge** | База знаний | Confluence integration |
| **Settings** | Конфигурация | Jira, Confluence, GitHub/GitLab |
| **JiraFieldsConfig** | Маппинг полей | Custom fields конфигурация |
| **Profile** | Профиль пользователя | Личные настройки |

#### 4.2.2 Компоненты (Components)

**Структурные**:
- `Layout.tsx` - главный layout с меню
- `RequireAuth.tsx` - защита маршрутов

**Информационные**:
- `EmptyState.tsx` - пустые состояния
- `DashboardSkeleton.tsx` - skeleton loading
- `TableSkeleton.tsx` - loading для таблиц
- `BackendStatusAlert.tsx` - статус backend

**Интеграционные**:
- `OnboardingWizard.tsx` - wizard настройки
- `IntegrationCard.tsx` - карточки интеграций
- `RepositoryStatus/` - статус репозиториев
- `SyncProgressDialog.tsx` - прогресс синхронизации
- `BackfillProgressDialog.tsx` - прогресс backfill операций

**Аналитические**:
- `KPIBar.tsx` - KPI метрики
- `VelocityChart.tsx` - chart velocity с trend line
- `AnalyticsFilters.tsx` - фильтры для аналитики
- `DashboardFilters.tsx` - фильтры dashboard

**Помощь & UX**:
- `HelpPanel.tsx` - справочная панель
- `HelpTooltip.tsx` - всплывающие подсказки
- `PageViewTracker.tsx` - отслеживание просмотров

**Трассируемость**:
- `traceability/nodes/` - узлы flow диаграммы
- `traceability/ImportExportDialog.tsx` - импорт/экспорт

#### 4.2.3 State Management

**Redux Toolkit store**:
```
store/
├── auth/ (authSlice)      # Аутентификация и пользователь
├── projects/ (projectSlice) # Проекты и их состояние
├── tasks/ (taskSlice)      # Задачи и фильтры
├── analytics/ (analyticsSlice) # Аналитика и метрики
└── ui/ (uiSlice)           # UI состояние (sidebar, dialogs, etc)
```

**React Query**: Для кэширования серверного состояния с auto-sync

#### 4.2.4 Services (Frontend)

- `api.ts` - axios instance с конфигурацией
- `auth.ts` - API calls для аутентификации
- `jira.ts` - Jira API calls
- `projects.ts` - Project API calls
- `analytics.ts` - Analytics API calls
- `traceability.ts` - Traceability API calls

---

## 5. КОНФИГУРАЦИЯ И НАСТРОЙКИ

### 5.1 Environment переменные

**Основные переменные** (`.env.example`):

#### Database
```env
POSTGRES_SERVER=localhost
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=po_helper
DB_POOL_SIZE=5
DB_POOL_MAX_OVERFLOW=10
```

#### Security
```env
SECRET_KEY=<генерируется командой>
ACCESS_TOKEN_EXPIRE_MINUTES=30
ENVIRONMENT=development
```

#### Jira Integration
```env
JIRA_BASE_URL=https://yourcompany.atlassian.net
JIRA_EMAIL=your-email@company.com
JIRA_API_TOKEN=your-api-token

# HTTP tuning (optional)
JIRA_HTTP_TIMEOUT=25              # seconds
JIRA_WORKLOG_TIMEOUT=30           # seconds
JIRA_HTTP_MAX_RETRIES=2           # retries
JIRA_HTTP_BACKOFF_SECONDS=1.0     # backoff

# Circuit breaker
JIRA_CB_ENABLED=true
JIRA_CB_THRESHOLD=3               # failures
JIRA_CB_SLEEP_SECONDS=30          # wait time
```

#### Confluence Integration
```env
CONFLUENCE_BASE_URL=https://yourcompany.atlassian.net/wiki
CONFLUENCE_EMAIL=your-email@company.com
CONFLUENCE_API_TOKEN=your-api-token
```

#### Celery & Redis
```env
REDIS_URL=redis://localhost:6379/0
CELERY_ENABLED=false
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
```

#### Git Integration
```env
GITHUB_WEBHOOK_SECRET=<webhook-secret>
GITLAB_WEBHOOK_SECRET=<webhook-secret>
GITHUB_API_TOKEN=<personal-access-token>
```

### 5.2 Docker Compose стек

**Сервисы** (`docker-compose.yml`):

```yaml
postgres:       # PostgreSQL 15 (основная БД)
redis:          # Redis 7 (кэш и очередь)
backend:        # FastAPI (REST API)
frontend:       # React + Vite (UI)
celery:         # Celery worker (фоновые задачи)
celery-beat:    # Celery scheduler (периодические задачи)
```

### 5.3 FastAPI конфигурация

**Основные настройки** (`backend/app/core/config.py`):

```python
class Settings(BaseSettings):
    PROJECT_NAME: str = "PO Helper"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"

    # Security
    SECRET_KEY: str  # Requires at least 32 chars
    ALGORITHM: str = "HS256"

    # Database
    DATABASE_URL: str  # SQLite or PostgreSQL

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]

    # Feature flags
    ENABLE_CONFLUENCE_AUTOLINK: bool = False
    ENABLE_MATRIX_CACHE: bool = False

    # Monitoring
    SENTRY_DSN: Optional[str] = None
```

### 5.4 Middleware и обработчики

**Зарегистрированный middleware** (`backend/app/core/middleware.py`):

1. **CORS** - Cross-Origin Resource Sharing
2. **Rate Limiting** - Ограничение частоты запросов (slowapi)
3. **Request Logging** - Логирование всех запросов
4. **Error Handling** - Централизованная обработка ошибок
5. **Metrics** - Prometheus метрики для мониторинга

---

## 6. ЗАВИСИМОСТИ ПРОЕКТА

### 6.1 Критические зависимости Backend

**Версионированные зависимости** (requirements.txt):

| Пакет | Версия | Критичность | Назначение |
|-------|--------|-----------|-----------|
| fastapi | 0.109.0 | КРИТИЧНАЯ | Web framework |
| sqlalchemy | 2.0.25 | КРИТИЧНАЯ | ORM |
| asyncpg | 0.29.0 | КРИТИЧНАЯ | Async PostgreSQL driver |
| celery | 5.3.6 | ВЫСОКАЯ | Task queue |
| redis | 5.0.1 | ВЫСОКАЯ | Cache & broker |
| atlassian-python-api | 3.41.4 | КРИТИЧНАЯ | Jira & Confluence API |
| pydantic | 2.5.3 | КРИТИЧНАЯ | Data validation |
| python-jose | 3.3.0 | ВЫСОКАЯ | JWT tokens |
| passlib | 1.7.4 | ВЫСОКАЯ | Password hashing |
| slowapi | 0.1.7 | СРЕДНЯЯ | Rate limiting |
| sentry-sdk | 1.40.6 | СРЕДНЯЯ | Error monitoring |

### 6.2 Критические зависимости Frontend

| Пакет | Версия | Назначение |
|-------|--------|-----------|
| react | 18.2.0 | UI framework |
| react-router-dom | 6.21.1 | Routing |
| @reduxjs/toolkit | 2.0.1 | State management |
| @tanstack/react-query | 5.17.9 | Server state sync |
| @mui/material | 5.15.3 | UI components |
| @mui/x-data-grid | 6.18.7 | Advanced tables |
| axios | 1.6.5 | HTTP client |
| chart.js | 4.4.1 | Charts |
| reactflow | 11.11.4 | Flow diagrams |

### 6.3 Potential Issues & Maintenance

**Outdated packages to monitor**:

```
Пакет                    Текущая    Рекомендация
─────────────────────────────────────────────────
slowapi                  0.1.7      → 0.1.9+ (есть альтернативы)
psycopg2-binary         2.9.9      → 3.1+ (новая версия)
atlassian-python-api    3.41.4     → latest (частые обновления)
```

**Security considerations**:
- Все credentials хранятся в `.env` (не в коде)
- Credentials для Jira/Confluence шифруются перед сохранением в БД
- JWT токены имеют expiration time (по умолчанию 30 минут)
- Rate limiting защищает от brute-force атак

---

## 7. API ENDPOINTS OVERVIEW

### 7.1 Основные категории endpoints

```
/api/v1/
├── /auth/                    # Аутентификация
│   ├── POST /login          # Логин
│   ├── POST /register       # Регистрация
│   └── POST /refresh        # Обновление токена
│
├── /projects/               # Управление проектами
│   ├── GET /                # Список проектов
│   ├── POST /               # Создание проекта
│   ├── GET /{id}            # Детали проекта
│   ├── PUT /{id}            # Обновление
│   └── DELETE /{id}         # Удаление
│
├── /tasks/                  # Управление задачами
│   ├── GET /                # Список задач
│   ├── POST /               # Создание задачи
│   ├── GET /{id}            # Детали задачи
│   ├── PUT /{id}            # Обновление
│   └── DELETE /{id}         # Удаление
│
├── /analytics/              # Аналитика и метрики
│   ├── GET /velocity        # Velocity data
│   ├── GET /burndown        # Burndown chart data
│   ├── GET /risks           # Risk assessment
│   ├── GET /forecast        # Прогноз завершения
│   └── GET /quality         # Quality metrics
│
├── /jira/                   # Jira интеграция
│   ├── POST /sync           # Синхронизировать проект
│   ├── GET /projects        # Список Jira проектов
│   ├── GET /issues          # Issues Jira проекта
│   └── POST /fields         # Маппинг custom fields
│
├── /traceability/           # Трассируемость
│   ├── GET /matrix          # Трассируемость матрица
│   ├── POST /rules          # Создание правила
│   ├── POST /execute        # Выполнить правило
│   └── GET /flows           # Flows трассируемости
│
├── /settings/               # Конфигурация
│   ├── GET /integrations    # Статус интеграций
│   ├── PUT /jira            # Jira credentials
│   ├── PUT /confluence      # Confluence credentials
│   └── PUT /github          # GitHub integration
│
├── /users/                  # Управление пользователями
│   ├── GET /                # Список пользователей
│   ├── POST /               # Создание пользователя
│   └── PUT /{id}            # Обновление роли
│
├── /health/                 # Мониторинг
│   ├── GET /                # Health check
│   ├── GET /ready           # Readiness probe
│   ├── GET /live            # Liveness probe
│   └── GET /metrics         # Prometheus метрики
│
├── /quality/                # Quality metrics
│   ├── GET /code-coverage   # Code coverage
│   ├── GET /bugs            # Bug rates
│   └── GET /tech-debt       # Technical debt
│
└── /testing/                # Testing integration
    ├── GET /testcases       # Test cases
    ├── GET /results         # Test results
    └── POST /sync           # Sync от TestRail
```

### 7.2 Async endpoints

```
/api/v1/
├── /tasks-async/            # Асинхронные операции
│   ├── POST /               # Создать фоновую задачу
│   ├── GET /{task_id}/status # Статус задачи
│   └── GET /{task_id}/result # Результат задачи
│
└── /jira/                   # Async Jira операции
    └── POST /projects/{id}/sync-async # Async sync
```

### 7.3 WebSocket endpoints

```
/api/v1/ws/
├── /projects/{id}           # Live updates для проекта
├── /sync/{project_id}       # Прогресс синхронизации
└── /notifications           # Уведомления в реальном времени
```

---

## 8. DATABASE SCHEMA (Key Tables)

### 8.1 User Management

```sql
-- Users table
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    email VARCHAR(255) UNIQUE,
    hashed_password VARCHAR(255),
    full_name VARCHAR(255),
    is_active BOOLEAN DEFAULT true,
    role ENUM('user', 'manager', 'admin'),
    created_at TIMESTAMP
);

-- Roles table
CREATE TABLE roles (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100),
    permissions JSON
);
```

### 8.2 Project Management

```sql
-- Projects
CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    name VARCHAR(255),
    jira_key VARCHAR(50),
    description TEXT,
    owner_id INTEGER FOREIGN KEY,
    created_at TIMESTAMP
);

-- Sprints
CREATE TABLE sprints (
    id INTEGER PRIMARY KEY,
    project_id INTEGER FOREIGN KEY,
    name VARCHAR(255),
    start_date DATE,
    end_date DATE,
    status ENUM('planning', 'active', 'closed')
);

-- Tasks
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY,
    project_id INTEGER FOREIGN KEY,
    sprint_id INTEGER FOREIGN KEY,
    jira_key VARCHAR(100),
    title VARCHAR(255),
    description TEXT,
    status ENUM('todo', 'in_progress', 'done'),
    story_points DECIMAL,
    assignee_id INTEGER FOREIGN KEY
);
```

### 8.3 Integration Settings

```sql
-- IntegrationSetting (для credentials)
CREATE TABLE integration_settings (
    id INTEGER PRIMARY KEY,
    project_id INTEGER FOREIGN KEY,
    integration_type ENUM('jira', 'confluence', 'github', 'gitlab'),
    encrypted_config TEXT,  -- зашифровано
    last_sync_at TIMESTAMP,
    status ENUM('connected', 'error', 'disconnected')
);
```

**Consolidation note**:
- `IntegrationSetting` хранит глобальные credentials по провайдеру.
- `ConnectorConfig` хранит project-scoped overrides и флаг включения.
- `Source` фиксирует runtime-данные коннектора (base_url/auth/scopes) для sync/health.

**TestRail mapping note**:
- Поле(я) с Jira ключами для связывания настраиваются через
  `ConnectorConfig.settings_json.testrail_jira_key_field` или
  `ConnectorConfig.settings_json.testrail_jira_key_fields` (по умолчанию `refs`).

### 8.4 Traceability

```sql
-- TraceabilityMatrix
CREATE TABLE traceability_matrix (
    id INTEGER PRIMARY KEY,
    project_id INTEGER FOREIGN KEY,
    source_artifact_id VARCHAR(100),  -- requirement, task, test, commit
    source_type ENUM('requirement', 'task', 'test', 'commit'),
    target_artifact_id VARCHAR(100),
    target_type ENUM('requirement', 'task', 'test', 'commit'),
    confidence_score DECIMAL(3,2),  -- 0.0 - 1.0
    created_at TIMESTAMP
);

-- TraceabilityRule
CREATE TABLE traceability_rules (
    id INTEGER PRIMARY KEY,
    project_id INTEGER FOREIGN KEY,
    name VARCHAR(255),
    source_pattern VARCHAR(255),
    target_pattern VARCHAR(255),
    rule_type ENUM('regex', 'keyword', 'semantic'),
    enabled BOOLEAN
);
```

---

## 9. НАИБОЛЕЕ ВАЖНЫЕ ФАЙЛЫ И КЛАССЫ

### 9.1 Backend (Top priority files)

**Критичные файлы для понимания архитектуры:**

1. **`backend/app/main.py`** (100 LOC)
   - Инициализация FastAPI приложения
   - Middleware регистрация
   - Sentry интеграция
   - CORS конфигурация

2. **`backend/app/core/config.py`** (80+ LOC)
   - Settings class с все переменные окружения
   - Database URL configuration
   - Feature flags

3. **`backend/app/services/jira/jira_service.py`** (500+ LOC)
   - Основной сервис для работы с Jira API
   - Синхронизация issues, sprints, boards
   - Error handling и retry logic

4. **`backend/app/services/sync/project_sync_orchestrator.py`**
   - Оркестрирует всю синхронизацию
   - Вызывает board_sync, issue_sync, worklog_sync

5. **`backend/app/api/api_v1/api.py`**
   - Главный router, инклюдит все endpoint роутеры

6. **`backend/app/models/project.py`**, **`task.py`**, **`user.py`**
   - Основные SQLAlchemy модели

### 9.2 Frontend (Top priority files)

**Критичные файлы для понимания UI:**

1. **`frontend/src/App.tsx`** (200 LOC)
   - Главное приложение
   - Роутинг между страницами
   - Redux и React Query инициализация

2. **`frontend/src/pages/Dashboard.tsx`**
   - Главная страница
   - Layout, KPI, charts, alerts

3. **`frontend/src/pages/Traceability.tsx`**
   - Страница трассируемости матрица

4. **`frontend/src/pages/TraceabilityFlowBuilder.tsx`**
   - Visual flow builder (используется reactflow)

5. **`frontend/src/store/` (Redux store)**
   - Redux slices для управления состоянием

6. **`frontend/src/services/api.ts`**
   - Axios instance и API calls

---

## 10. ПРОЦЕССЫ И WORKFLOWS

### 10.1 Синхронизация Jira (Critical Path)

```
User clicks "Sync Project" in UI
         │
         ▼
Frontend: POST /api/v1/jira/projects/{id}/sync
         │
         ▼
Backend: JiraController.sync_project()
         │
         ├─ Validate project & credentials
         │
         ▼
         ├─ Call JiraService.sync_project()
         │  │
         │  ├─ Fetch project from Jira API
         │  ├─ Fetch all sprints
         │  ├─ Fetch all issues for each sprint
         │  ├─ Fetch worklogs for each issue
         │  └─ Apply circuit breaker if failures
         │
         ├─ Transform data to internal models
         │
         ├─ Store in PostgreSQL
         │
         ├─ Trigger analytics calculation
         │
         └─ Return success/error

         ▼
Frontend: Show sync result (success or error message)
```

### 10.2 Вычисление аналитики

```
Trigger: Project synced OR User requests analytics
         │
         ▼
AnalyticsService.calculate_metrics(project_id)
         │
         ├─ Query completed sprints from DB
         ├─ Calculate velocity (story points per sprint)
         ├─ Calculate completion rate
         ├─ Predict future velocity (moving average)
         ├─ Forecast project completion date
         ├─ Identify risks & blockers
         └─ Cache results in Redis

         ▼
Result stored in memory cache with TTL 300 seconds
```

### 10.3 Трассируемость (Traceability Flow)

```
User creates TraceabilityRule
         │
         ▼
RuleExecutionEngine.execute_rule(rule_id)
         │
         ├─ Fetch all requirements matching source_pattern
         ├─ For each requirement:
         │  └─ Find matching tasks by pattern matching
         │     └─ For each task:
         │        └─ Find matching tests
         │           └─ Find matching commits
         │
         ├─ Calculate confidence_score for each link
         ├─ Store in TraceabilityMatrix
         └─ Mark as complete

         ▼
Matrix displayed in Traceability page with status
```

---

## 11. РАЗВЕРТЫВАНИЕ (DEPLOYMENT)

### 11.1 Development Environment

```bash
# 1. Clone repository
git clone <repo>
cd po_helper

# 2. Setup backend
cd backend
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt

# 3. Setup frontend
cd ../frontend
npm install

# 4. Copy environment file
cp ../.env.example ../.env
# Edit .env with Jira credentials

# 5. Run services
# Terminal 1: Backend
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2: Frontend
cd frontend
npm run dev  # Starts on http://localhost:5173

# Access:
# Frontend: http://localhost:5173
# API: http://localhost:8000
# Docs: http://localhost:8000/docs
```

### 11.2 Docker Development

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f backend

# Access:
# Frontend: http://localhost:3000
# API: http://localhost:8000
# Docs: http://localhost:8000/docs
```

### 11.3 Production Deployment

```bash
# Build production images
docker-compose -f docker-compose.prod.yml build

# Deploy with environment variables configured
docker-compose -f docker-compose.prod.yml up -d
```

---

## 12. КЛЮЧЕВЫЕ ОСОБЕННОСТИ И ИННОВАЦИИ

### 12.1 Advanced Features

1. **Circuit Breaker для Jira**
   - Предотвращает cascading failures при Jira outages
   - Автоматически открывает circuit после N ошибок
   - Держит circuit открытым для M секунд

2. **Асинхронная синхронизация (Celery)**
   - Фоновые задачи для длительных операций
   - Periodic sync через celery-beat scheduler
   - Progress tracking в реальном времени (WebSocket)

3. **Трассируемость артефактов**
   - Связь Requirements → Tasks → Tests → Commits
   - Confidence scoring для каждой связи
   - Правила с regex/keyword/semantic matching

4. **RBAC (Role-Based Access Control)**
   - User, Manager, Admin roles
   - Granular permissions для операций
   - Audit logging всех действий

5. **Encrypted Credentials**
   - Все credentials шифруются перед сохранением в БД
   - Decryption только при использовании
   - Support для различных auth strategies (Email+Token vs PAT)

### 12.2 Performance Optimizations

- **Redis caching** для аналитики (TTL 300 сек)
- **Database connection pooling** (asyncpg)
- **Rate limiting** для защиты API
- **React.memo** для оптимизации компонентов
- **Virtual scrolling** в таблицах (DataGrid)
- **Lazy loading** страниц (React Router)

### 12.3 Developer Experience

- **Swagger UI** для API documentation (`/docs`)
- **Type-safe** frontend (TypeScript)
- **Pydantic schemas** для валидации
- **Hot reload** в development mode
- **E2E tests** с Puppeteer

---

## 13. РЕКОМЕНДАЦИИ И ЗАКЛЮЧЕНИЕ

### 13.1 Strengths

✅ **Архитектура**: Clean Architecture с четкой разделением слоев
✅ **Интеграции**: Robust Jira/Confluence integration с error handling
✅ **Безопасность**: JWT auth, RBAC, encrypted credentials
✅ **Производительность**: Async/await, caching, rate limiting
✅ **Масштабируемость**: Celery для async tasks, Redis cache, микросервисная готовность
✅ **UX**: Material Design, rich charts, real-time feedback
✅ **Мониторинг**: Sentry integration, health checks, Prometheus metrics

### 13.2 Areas for Improvement

⚠️ **Документирование**:
- Добавить docstrings во все сервисы
- Создать ADR (Architecture Decision Records)
- Пополнить API документацию примерами

⚠️ **Тестирование**:
- Увеличить coverage (unit + integration tests)
- E2E тесты для критичных flows

⚠️ **Мониторинг**:
- Более детальные метрики для Jira requests
- Алерты на excessive failures

⚠️ **Оптимизация**:
- Пересмотреть размер batch запросов к Jira
- Реализовать incremental sync (не полную resync)

### 13.3 Scalability Path

**Для масштабирования**:
1. Отделить Jira sync в микросервис
2. Реализовать WebSocket broadcasts через Redis
3. Использовать Kafka для event streaming
4. Добавить GraphQL для более гибких queries
5. Горизонтальное масштабирование backend через load balancer

### 13.4 Next Steps

1. **Завершить миграцию на PostgreSQL** (текущего SQLite)
2. **Добавить TestRail и Confluence full integration**
3. **Реализовать GitHub/GitLab API интеграцию**
4. **Улучшить UI/UX** в соответствии с Material Design v5
5. **Покрыть критичный код тестами**

---

## БЫСТРЫЕ ССЫЛКИ

### Запуск приложения
- **Frontend dev**: `npm run dev` (порт 5173)
- **Backend dev**: `uvicorn app.main:app --reload` (порт 8000)
- **Docker**: `docker-compose up -d`

### Документация
- **API Docs**: http://localhost:8000/docs
- **Backend**: `c:\Users\Use\IdeaProjects\po_helper\backend\`
- **Frontend**: `c:\Users\Use\IdeaProjects\po_helper\frontend\`

### Важные файлы
- **Settings**: `backend/app/core/config.py`
- **Jira Service**: `backend/app/services/jira/jira_service.py`
- **Main App**: `frontend/src/App.tsx`
- **Docker Compose**: `docker-compose.yml`

---

**Отчет составлен**: 9 декабря 2025
**Версия приложения**: 1.0.0
**Статус**: Fully Operational
