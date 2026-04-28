# PO Helper — Backend (Confluence + Jira)

Краткое описание: бэкенд сервиса «PO Helper» для интеграции с Confluence и Jira, чтобы у Product Owner был единый контекст решений (PRD/ADR/Research), видимость динамики изменений, покрытие требований задачами Jira и объединённый Intelligent‑дашборд.

## Цель и фокус
- Контекст решений: PRD / ADR / Research в одном месте.
- Динамика: свежесть документации, существенные изменения, тренды.
- Покрытие: соответствие требований PRD с задачами Jira.
- Дашборд: сводные метрики и actionable‑инсайты для PO.
- Единицы измерения: старт в «часах» (как сейчас), позже — опция Story Points.

## Стек и архитектура
- Веб: FastAPI + Uvicorn.
- Данные: SQLAlchemy 2.x (по умолчанию SQLite: `sqlite+aiosqlite`), Alembic (в полном профиле зависимостей).
- Интеграции: `requests` (REST + CQL), `beautifulsoup4` (парсинг Confluence storage XHTML).
- Конфигурация: `pydantic-settings` (Pydantic v2).
- Безопасность: JWT (`python-jose[cryptography]`), `passlib[bcrypt]`, CORS.

Стартовая структура:
- Приложение: `backend/app/main.py` (инициализация FastAPI, CORS, роуты).
- Роутер API V1: `backend/app/api/api_v1/api.py`.
- Эндпоинты: `backend/app/api/api_v1/endpoints/` (в т.ч. `confluence.py`).
- Сервисы: `backend/app/services/` (в т.ч. `confluence_service.py`).
- Настройки: `backend/app/core/config.py`.

## Переменные окружения (.env)
- Базовые: `SECRET_KEY`, `ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `DATABASE_URL`.
- Confluence: `CONFLUENCE_BASE_URL`, `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN`.
  - Режимы аутентификации: PAT (Bearer) или Basic (email + API token).
  - Авто‑детект: добавление `/wiki` при необходимости.
- CORS: `CORS_ORIGINS`.

## Реализованные эндпоинты (V1)
Префикс: `/api/v1`.

Confluence (`backend/app/api/api_v1/endpoints/confluence.py`):
- `POST /confluence/connect` — подключение и валидация (JSON body, REST `latest`/`v2`).
- `GET  /confluence/status` — состояние подключения (configured, base_url, auth_mode).
- `GET  /confluence/search?cql=...&limit=...` — CQL‑поиск, список страниц (id, title, type, url, version, last_updated).
- `GET  /confluence/pages/{page_id}` — метаданные + HTML (storage) + labels.
- `GET  /confluence/prd/{page_id}/requirements` — извлечение требований из PRD‑таблиц (`confluenceTable`).

Прочие группы роутов заготовлены: `auth`, `users`, `projects`, `tasks`, `jira`, `analytics`, `settings`.

## Текущий статус (Фазы 1–2, MVP)
- Сервис Confluence (`confluence_service.py`): PAT/Basic, авто‑детект `/wiki`, REST `latest`/`v2`, таймауты, безопасное логирование.
- Эндпоинты Confluence: подключение, статус, поиск (CQL), получение страницы, извлечение PRD‑требований из таблиц.
- Минимальные зависимости: `backend/requirements-minimal.txt` (включая `beautifulsoup4`).

## Дорожная карта (Фазы 0–10)
- Фаза 0. Подготовка
  - Env‑креды, режимы PAT/Basic; авто‑детект `/wiki`.
  - Поддержка Cloud/DC; REST v2/latest + CQL; fallback при 3xx/HTML.
- Фаза 1. Бэкенд: базовая интеграция (ГОТОВО в части Confluence)
  - Модели: `ConfluencePage`, `ConfluenceSpace` (скоуп на MVP — в памяти/без БД).
  - Эндпоинты: connect/status/search/pages.
- Фаза 2. Бэкенд: синхронизация контента
  - Синк по space/CQL; пагинация; `updated > last_sync_at`.
  - Сохранение HTML (storage) + «сырой» JSON; простая индексация (title/headers/cells).
  - Idempotency, таймауты, лог по страницам/байтам.
- Фаза 3. Извлечение артефактов
  - PRD: таблицы (ID/Requirement/Priority/Acceptance), макросы → `Requirement`.
  - ADR: секции (Context/Decision/Consequences/Alternatives/Status) → `ADR`.
  - Research/Feedback: инсайты по категориям → `Insight`.
  - Эндпоинты: `/confluence/prd`, `/confluence/adr`, `/confluence/research`.
- Фаза 4. Связка с Jira (coverage)
  - Матрица покрытия: `Requirement` ↔ Jira issues (точное ID + fuzzy по описанию).
  - Модель `RequirementLink`, агрегат `Coverage`, эндпоинт `/product-intelligence/{project_id}/coverage`.
- Фаза 5. UI: Обзор Confluence
  - Settings (PAT/Basic, Test), вкладка Knowledge (поиск, списки PRD/ADR/Research, переходы).
  - PRD Viewer: таблица требований + статус покрытия (Linked/Uncovered).
- Фаза 6. UI: Product Intelligence Dashboard
  - Coverage %, orphan Jira, ADR статус, инсайты пользователей, изменения доков (30/90 дней).
- Фаза 7. Автоматизация и уведомления
  - Планировщик еженедельных проверок, webhook/email, ручной запуск `/confluence/checks/run?name=`.
- Фаза 8. Производительность и надёжность
  - Пагинация, rate‑limit, retries, лимит параллельности, кэш ETag/If‑Modified‑Since.
- Фаза 9. Безопасность и соответствие
  - Не логируем токены, шифрование хранения, маскирование в `/settings`, доступ по space/project.
- Фаза 10. Приёмочные критерии
  - Подключение (OK v2/v3), синк (инкрементальный, 1000+ страниц), парсинг (>=80% PRD), coverage, UI‑блоки, округление и обрезка текстов.

## Технические детали
- Confluence REST: прямые вызовы `requests` + CQL; fallback при нестандартных ответах.
- Парсинг: `BeautifulSoup` по XHTML (storage), обработка таблиц/заголовков/макросов (по мере расширения).
- Jira сопоставление: точное совпадение `req_id` + эвристики по описанию (fuzzy‑match), локальный индекс.
- Логи: без токенов; в `/settings` токен не возвращается.

## Запуск локально (Windows PowerShell)
```pwsh
cd backend
# Минимальные зависимости
.venv\Scripts\python -m pip install -r requirements-minimal.txt
# (опционально) Полный профиль
# .venv\Scripts\python -m pip install -r requirements.txt

# Запуск
.venv\Scripts\Activate.ps1
$env:BACKEND_BIND_HOST = "127.0.0.1"
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Проверка: `GET /health`, документация: `GET /api/v1/docs`.

Для local demo:
- backend должен слушать только `127.0.0.1`;
- `ALLOW_UNAUTHENTICATED_DEMO_API=false` по умолчанию;
- для сохранения Jira/Confluence токенов нужен отдельный `ENCRYPTION_SECRET`.

## Быстрые сценарии проверки Confluence
- Подключение (PAT):
- `curl -X POST http://127.0.0.1:8000/api/v1/confluence/connect -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d "{\"base_url\":\"https://<org>.atlassian.net\",\"api_token\":\"<pat>\"}"`
- Подключение (Basic):
- `curl -X POST http://127.0.0.1:8000/api/v1/confluence/connect -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d "{\"base_url\":\"https://<org>.atlassian.net\",\"email\":\"user@org\",\"api_token\":\"<token>\"}"`
- Статус: `GET /api/v1/confluence/status`.
- Поиск (CQL): `GET /api/v1/confluence/search?cql=text%20~%20%22PRD%22%20ORDER%20BY%20lastmodified%20DESC`.
- Страница: `GET /api/v1/confluence/pages/{page_id}`.
- PRD требования: `GET /api/v1/confluence/prd/{page_id}/requirements`.

## Следующие шаги
1) Синк страниц в БД + простая индексация (title/headers/cells).
2) Парсинг ADR/Research в модели и эндпоинты.
3) Покрытие с Jira (точное/эвристическое сопоставление) + агрегаты.
4) UI: Settings + Knowledge + первый дашборд.
5) Автоматизация: планировщик и проверки свежести/покрытия.

---
Вопросы/уточнения: если есть примеры PRD/ADR страниц (шаблоны), пришлите ссылки/HTML — учту в правилах парсинга для повышения точности.

