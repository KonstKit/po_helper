# Roadmap: устранение Should Fix (Major) — po_helper

Источник: staff code review (Level 4 audit, 2026-08-28) + актуализировано после
работы по Blocker'ам (ветка `fix/security-blockers-b1-b5`) и трёх раундов
ревью Codex. Все ссылки на строки — состояние на момент аудита; в `auth.py`
после правок B1 искать по символам.

## Что уже закрыто и НЕ входит в этот роадмап

| Находка | Закрыта в |
|---|---|
| OAuth state/redirect/email-linking (B1) | `2c5211a`, `5329fcf` |
| WebSocket без аутентификации (B2) + JWT в WS query (MF1 r1) | `acc360d`, `b1984b9` (one-time ticket) |
| Permission-гейты jira/confluence (B3) | `ca5a610` |
| Утечка `str(e)` для 5xx и IntegrityError 409 (B4, MF2 r1) | `958c03f`, `24f6180` |
| slowapi 500 на 10 эндпоинтах (B5) | `6c8cd2e` |
| Microsoft email_verified / cookie hardening / connect_pat (SF r1) | `5329fcf` |

Верификационный бейзлайн: pytest 528 passed, ruff/mypy/tsc чистые.

---

> Статус: **волна A выполнена** (PR #7), **волна B выполнена** (PR #8),
> **волна C выполнена** (PR #9), **волна D выполнена** (D1: flow-валидация,
> PRD-парсер и coverage-аналитика вынесены в сервисы; D2: rollback-контракт
> get_db; D3: retry-политика для всех Celery-задач + выровненные дефолты;
> D4: silent-except baseline 147 + non-regression гейт), **волна E выполнена**
> (E1: React Query провайдер + useProjects, 5 страниц мигрированы; E2: cancelled-гварды
> Analytics/Testing; E3: 22×void err → логирование; E4: RFC docs/RFC_JWT_STORAGE.md;
> E5: types.ts 1856 строк → 9 доменных модулей + барель). E6 (ProjectDetail
> декомпозиция) — follow-up.
> Статус волн: A выполнена (PR #7), B выполнена (PR #8), C выполнена (PR #9,

> забатчены; C2: закрыт ревертом — owner сериализуется как owner_id,
> N+1 не существовал; C3: bounded locks + Redis single-flight с атомарным
> Lua-релизом + WARNING-деградация). Покрытие тестами-счётчиками: rules,
> health, analysis, metrics, ci, suggestions, jira-fields (import);
> calibrate требует живой Jira и покрыт косвенно.
> (ветка feat/should-fix-wave-b: B1 шифрование MFA + хэш кодов с
> upgrade-on-read, B2 TOTP anti-replay, B3 Redis rate limiter + RATE_LIMIT_*
> + proxy-headers, B4 ALLOW_DEBUG_DEMO_USER, B5 запрет plaintext-fallback).

## Волна A — быстрые победы (дни 1–3, низкий риск)

Критерий включения: точечные правки, нет миграций данных, нет RFC.

### A1. `SECRET_KEY`-placeholder не должен проходить валидатор
- **Проблема:** `config.py:24` — default `"your-secret-key-here-change-in-production"`
  проходит валидатор длины: инстанс поднимется с известным всему миру ключом.
- **Шаги:** startup-guard в `main.py` (по образцу guard'а
  `ALLOW_UNAUTHENTICATED_DEMO_API`, `main.py:238-256`): `RuntimeError`, если
  `SECRET_KEY` равен дефолтному значению и `ENVIRONMENT` не `development`/`test`.
- **DoD:** тест: приложение не стартует в `ENVIRONMENT=production` с дефолтным ключом.
- **Усилие:** S (0.5 дня). **Риск:** низкий.

### A2. MFA `temp_token` из query string в body
- **Проблема:** `verify_mfa_login` принимает `temp_token: str = Query(...)`
  (auth.py:959), фронтенд дублирует (users.ts:213) — токен оседает в
  access-логах прокси и истории.
- **Шаги:** добавить `temp_token` в body-модель `MFAVerifyRequest` → убрать
  `Query`-параметр; фронтенд — POST body; совместимость: один релиз принимать
  оба варианта, затем убрать query.
- **DoD:** тест verify-login с body; grep по репо не находит `temp_token=`.
- **Усилие:** S. **Риск:** низкий (задействован только MFA-флоу).

### A3. Блокирующий `requests.*` в async-эндпоинтах → `asyncio.to_thread`
- **Проблема:** блокировка event loop всего воркера: `settings.py:555/571`
  (GitHub), `settings.py:765` (GitLab), `settings.py:892` (TestRail),
  `quality/gates.py:169` и `:256` (`requests.post`).
- **Шаги:** механическая замена по образцу уже существующего
  `await asyncio.to_thread(...)` (`settings.py:193-194`).
- **DoD:** grep `requests\.` внутри `async def` — 0 совпадений; смоук
  `POST /settings/gitlab/test` не блокирует параллельный `/health`.
- **Усилие:** S. **Риск:** низкий.

### A4. Критичные silent `except` → логирование
- **Проблема:** 85 полностью silent `except Exception` без логов; худшие —
  `settings.py` (20 шт., 14 silent: 135, 487, 711, 776, 991), молча
  проглатывающие ошибки СОХРАНЕНИЯ настроек интеграций.
- **Шаги (только критичные, не трогая семантику):** добавить
  `logger.warning("... failed: %s", e)` в settings.py (все 14) и в
  `services/sync/project_sync_orchestrator.py` (480/546/559/586 — `return None`,
  688 — `pass`). Остальные 60+ — в волне D.
- **DoD:** grep-скрипт счётчика silent-except в settings.py = 0; новые тесты не
  требуются (поведение не меняется).
- **Усилие:** S–M. **Риск:** низкий (только добавление логов).

### A5. Индексы на FK без индексов (миграция 037)
- **Проблема:** `LegacyMapping.new_artifact_id` (traceability.py:173),
  `SuggestedLink.from_artifact_id/to_artifact_id` (:216, :218),
  `Artifact.parent_version_id` (:57) — join'ы и delete по ним → seq scan.
- **Шаги:** alembic-миграция `op.create_index` на 4 колонки; в модели —
  `index=True`. Для PG — обычный `CREATE INDEX` (таблицы небольшие).
- **DoD:** миграция вверх/вниз на SQLite и PostgreSQL; `EXPLAIN` delete-цикла
  из `health.py` использует index.
- **Усилие:** S. **Риск:** низкий. **Зависимость:** PostgreSQL-стенд для проверки.

**Итог волны A:** ~2–3 дня, заметное снижение риска без архитектурных решений.

---

## Волна B — безопасность второго эшелона (недели 1–2)

### B1. MFA-секреты: шифрование и хэширование (миграция данных)
- **Проблема:** TOTP-секрет и backup codes лежат plaintext:
  `models/user.py:40-41` (`mfa_secret`, `mfa_backup_codes` JSON);
  `mfa.py:210-212` — `hash_backup_codes` возвращает коды без хэширования
  (комментарий в коде это признаёт).
- **Шаги:**
  1. `mfa_secret` → `encrypt_integration_secret` (AES-GCM инфраструктура уже
     есть, требует `ENCRYPTION_SECRET`).
  2. Backup codes → хранить SHA-256-хэши; сравнение по хэшу
     (сейчас `secrets.compare_digest` по plaintext — заменить на
     digest-сравнение, семантика «одноразовости» сохраняется).
  3. Миграция данных: при чтении пользователя со старым форматом —
     перешифровать secret, backup codes переиздать нельзя → инвалидировать и
     потребовать повторную генерацию (безопаснее, чем перенос plaintext).
- **DoD:** тесты roundtrip шифрования, инвалидация старых кодов; в БД нет
  plaintext (инспекция дампа в тесте).
- **Усилие:** M (2–3 дня). **Риск:** средний — затрагивает MFA-логин;
  обязательный прогон e2e MFA-флоу. **Зависимость:** `ENCRYPTION_SECRET` в
  deployment.

### B2. TOTP anti-replay
- **Проблема:** `mfa.py:169` — `totp.verify(code, valid_window=1)` без
  last-used: один код принимается повторно ~90 сек (включая verify-login).
- **Шаги:** колонка `mfa_last_used_counter` (Int); принимать только
  `totp.counter_at_time(code) > last_used` (PyJWT/pyotp дают
  `TOTP.verify(..., valid_window)` — использовать
  `totp.verify(code)` + явный расчёт counter через `timecode`); обновлять при
  успехе в той же транзакции.
- **DoD:** тест: повторная отправка того же кода → 401.
- **Усилие:** S. **Риск:** низкий (пограничный clock-skew — протестировать).

### B3. Rate limiter: реальная, а не декоративная защита
- **Проблема:** slowapi in-memory per-process (лимит × N воркеров), ключ по
  socket peer — за nginx все клиенты один IP; `swallow_errors=True`; у
  jira/confluence лимитов нет; env `RATE_LIMIT_DEFAULT/AUTH/SYNC` объявлены в
  `.env`, но в `config.py` не существуют (dead config).
- **Шаги:**
  1. Подключить shared storage: `Limiter(storage_uri=settings.REDIS_URL)`.
  2. Корректный клиентский IP за прокси: `--proxy-headers` +
     `forwarded_allow_ips` в uvicorn-командах compose; проверить, что
     `get_remote_address` видит реальный IP.
  3. Объявить `RATE_LIMIT_*` в `config.py`, применить
     `RATE_LIMIT_SYNC` к jira/confluence sync-эндпоинтам (декораторы).
  4. `swallow_errors` оставить True, но залогировать отказ лимитера на WARNING.
- **DoD:** интеграционный тест: 2 параллельных «воркера» (потока) с общим
  storage — суммарный лимит соблюдён; sync-эндпоинт отдаёт 429.
- **Усилие:** M. **Риск:** средний (нужен доступный Redis; при его отсутствии —
  оставить memory-fallback с WARNING).

### B4. DEBUG-демо-админ → явный отдельный флаг
- **Проблема:** `deps.py:288-296` — при `DEBUG=true` ЛЮБОЙ запрос без
  Authorization получает admin-пользователя. Prod-guard есть, но dev-инстанс,
  доступный в сети, — полный admin.
- **Шаги:** новый `ALLOW_DEBUG_DEMO_USER: bool = False`; demo-fallback только
  при нём; каждый вход — `logger.warning` с IP; `DEBUG` больше не даёт доступ.
- **DoD:** тест: `DEBUG=true` + флаг False → 401; флаг True → 200 + warning.
- **Усилие:** S. **Риск:** низкий (update dev-workflows, где полагались на DEBUG).

### B5. Crypto: запретить молчаливый plaintext-fallback
- **Проблема:** `encrypt_str` при отсутствии обоих секретов возвращает
  plaintext без предупреждения (`crypto.py:120-121`; используется для GitHub
  token bundle, settings.py:470) — секрет может молча лечь в БД открытым.
- **Шаги:** `RuntimeError` при выключенных секретах (по образцу
  `encrypt_integration_secret`, crypto.py:131-134); для
  `ENCRYPTION_SECRET`-миграции — руководство в DEPLOYMENT.md.
- **DoD:** тест: сохранение GitHub-токена без секретов → явная ошибка 500
  generic + WARNING в логах.
- **Усилие:** S. **Риск:** низкий; KDF-усиление (SHA-256 → HKDF) — ОТДЕЛЬНО и
  только с ротацией `ENCRYPTION_SECRET_PREVIOUS` (ломает совместимость).

---

## Волна C — производительность (недели 2–3)

### C1. N+1 в горячих путях (по убыванию боли)
| Место | Проблема | Фикс |
|---|---|---|
| `traceability/rules.py:580-584` | select правила на каждый execution, до 1001 запроса при limit=1000 | один `select(...).where(id.in_(...))` + словарь |
| `traceability/health.py:1131-1188` | `db.delete` в цикле + select на каждую группу дубликатов | bulk `delete().where(id.in_())`, batch-select |
| `traceability/analysis.py:421-429` | запрос на каждый узел фронтера BFS | уровневый batch: собрать frontier → один IN-запрос |
| `git/metrics.py:406-414` | existence-check select на каждый sha | `in_()` + set |
| `git/ci.py:306-316` | select на каждый artifact_id | `in_()` + set |
| `traceability/suggestions.py:480` | select на каждый sugg_id (до 100) | `in_()` + словарь |
| `jira_fields.py:86, :317` | select в цикле | batch |
| `services/traceability/link_service.py:322` | flush+select на каждый элемент батча | собрать → один select → bulk insert |
- **DoD (на каждый пункт):** воспроизводимый замер счётчика запросов
  (SQLAlchemy event listener в тесте) «до/после»; функциональные тесты зелёные.
- **Усилие:** M (3–4 дня суммарно). **Риск:** средний — изменения в
  traceability-логике; по одному PR на файл.

### C2. Eager-loading политика
- **Проблема:** `joinedload` — 0 использований; `selectinload` только для
  `User.roles`; ленивые отношения в читаемых эндпоинтах дают скрытые N+1.
- **Шаги:** аудит связей в часто читаемых моделях (Project→owner, Task→assignee,
  Artifact→project); добавить `selectinload` в списках; при необходимости —
  `lazy="raise_on_sql"` в тестах для выявления новых N+1.
- **DoD:** тест с `lazy="raise"` не падает на ключевых list-эндпоинтах.
- **Усилие:** M. **Риск:** низкий.

### C3. Кэш: leaks и thundering herd
- **Проблема:** `cache_enhanced.py:530` — `Dict[str, asyncio.Lock]` без
  очистки (утечка на уникальных ключах); per-key lock процесс-локальный — при
  нескольких процессах защита не работает; деградация Redis логируется на
  DEBUG (582, 661, 683) — незаметна.
- **Шаги:** bounded-очистка locks (по завершении waiters); распределённая
  блокировка Redis `SET NX EX` с локальным fallback; уровень логов → WARNING.
- **DoD:** тест на рост словаря locks при 10k уникальных ключей (константа);
  тест single-flight при 50 конкурентных miss.
- **Усилие:** M. **Риск:** средний (центральный компонент), нужен Redis-стенд.

---

## Волна D — архитектура backend (недели 3–5, по одному модулю на PR)

### D1. God-роутеры → тонкие роутеры + сервисы
1. **`rules.py` (1299):** вынести движок валидации React-Flow графов
   (`validate_flow` 99 строк, `_validate_node_configuration` 144 строки) в
   `services/traceability/flow_validator.py`; роутер — только HTTP-связка.
2. **`confluence.py` (1157):** PRD-парсер (`extract_prd_requirements` 296
   строк + BeautifulSoup-утилиты) → `services/confluence_prd_parser.py`.
3. **`testing.py` (1205):** coverage-агрегация (`calculate_component_coverage`
   120, `get_delta_coverage` 107, `detect_flaky_tests` 95) →
   `services/testing_analytics.py`.
- **DoD каждого:** поведение сохранено (текущие тесты зелёные, счётчик строк
  роутера < 400); новые unit-тесты на сервис (без HTTP).
- **Усилие:** L (по 2–3 дня на модуль). **Риск:** средний; строгий запрет на
  «заодно рефакторинг» смежного кода.

### D2. Единый транзакционный паттерн
- **Проблема:** три стиля одновременно: `db.begin()` (14), явный `commit()`
  (68), `transactional_session` (87); `get_db` (database.py:78-83) —
  commit/rollback вне контракта; `link_service` flush'ит и полагается на
  коммит вызывающего.
- **Шаги:** RFC на 1 страницу (паттерн-стандарт: `transactional_session` для
  всего, что пишет); миграция кода по эпикам (не big-bang); в `get_db` —
  `rollback` в finally для гарантии освобождения; контракт `link_service`
  (flush без commit) — зафиксировать в docstring и типах.
- **DoD:** grep-аудит: `await db.commit()` вне `transactional_session` → 0 в
  endpoints; тест на rollback при исключении в середине транзакции.
- **Усилие:** L, распределить по волнам. **Риск:** высокий на переходный период
  — маленькими PR.

### D3. Celery: retry и консистентность
- **Проблема:** retry-политика только у 3 из 20 задач (export, confluence,
  jira); несогласованные fallback-дефолты `CELERY_ENABLED` (`jira.py` — True,
  `testrail.py`/`post_sync.py` — False); `confluence.py:539` диспатчит
  `.delay()` без guard — упадёт при выключенном Celery.
- **Шаги:** общий декоратор/фабрика задач (`bind=True, max_retries=3,
  acks_late=True, reject_on_worker_lost=True`) + `autoretry_for` по типам;
  выровнять дефолты на `settings.CELERY_ENABLED`; guard-хелпер
  `dispatch_or_inline(...)`.
- **DoD:** тесты dispatch-фолбэков (по образцу `test_jira_sync_dispatch.py`);
  метрика `celery_task_retries` в dashboard.
- **Усилие:** M. **Риск:** низкий.

### D4. Остаток silent excepts + stacktraces
- После A4: оставшиеся ~60 silent `except` (confluence_service 13,
  board_service 11, webhook_processor 11, …) → логирование с контекстом;
  ~97 `logger.error` без stacktrace → `exc_info=True` в hot paths.
- **DoD:** CI-скрипт `scripts/check_silent_excepts.py` с baseline-файлом,
  запрещающий рост.
- **Усилие:** M. **Риск:** низкий.

---

## Волна E — frontend (недели 4–6)

### E1. Серверное состояние: внедрить React Query (или удалить его)
- **Проблема:** `@tanstack/react-query` установлен и не используется (0
  вхождений); самописный TTL-кэш в Redux (`dataThunks.ts` с module-level
  promise-guard'ами, `taskSlice.lastLoadedAtByProject`, `sprintSlice`) + 6
  копий «загрузи проекты при монтировании» (`Analytics/Quality/Tasks/Testing/
  Projects/Traceability.tsx`); `useSelectedProject.ts:58-64` комментарием
  фиксирует гонки между путями.
- **Шаги:** RFC-решение (рекомендация — внедрять); поэтапно: projects →
  tasks → sprints → traceability; `QueryClientProvider` в index.tsx; хук
  `useProjects()` заменяет 6 копий; удалить самописный TTL-кэш и
  promise-guard'ы после миграции последних потребителей.
- **DoD:** grep `listProjects()` в pages — только через хук; тесты страниц
  переписаны на msw-моки QueryClient; бандл не вырос (>5KB — вынести в чанк).
- **Усилие:** L (4–5 дней). **Риск:** средний; по странице за PR.

### E2. Race conditions на переключениях
- **Проблема:** `Analytics.tsx:108-170` — 11 параллельных запросов без
  cancelled (поздний ответ затирает данные нового проекта);
  `Testing.tsx:122-196`, `Traceability.tsx:227-246` — аналогично.
- **Шаги:** паттерн из `Dashboard.tsx:298-346` (AbortController +
  requestId-ref) перенести в три файла; ESLint-правило
  `react-hooks/exhaustive-deps` без disable.
- **DoD:** unit-тест с задержанным ответом (msw) — состояние не затирается.
- **Усилие:** S–M. **Риск:** низкий.

### E3. `void err` в ProjectDetail (22 штук)
- **Проблема:** ошибки спринт-инсайтов/quality-gate молча проглатываются
  (`ProjectDetail.tsx:690-702, 733, 800-802, ...`).
- **Шаги:** единый `handleSilentError(label)` → snackbar/telemetry
  (образец — `emitDashboardRuntimeWarning`); 22 замены.
- **DoD:** grep `void err` = 0; e2e: при падении insights виден fallback.
- **Усилие:** S. **Риск:** низкий.

### E4. Хранение JWT → httpOnly cookie + refresh (RFC)
- **Проблема:** JWT в localStorage (XSS-доступен), refresh-токенов нет —
  401 всегда разлогин; `client.ts:7` заявляет "auth refresh", реализации нет.
- **Шаги:** RFC: httpOnly SameSite=Strict cookie от backend + короткий
  access-token + refresh-эндпоинт + revocation-таблица; последствия для
  Vite-прокси и e2e; альтернатива — принятый риск с CSP-ужесточением.
- **DoD:** RFC-approved; при внедрении — e2e логина, истечения, logout-all.
- **Усилие:** RFC S; внедрение L. **Риск:** высокий (затрагивает весь auth) —
  только после E1.

### E5. `types.ts` (1856 строк, 166 типов) → по доменам
- **Шаги:** механическое разбиение `types.ts` на `types/{project,task,
  sprint,traceability,quality,testing,analytics,integrations}.ts` с
  реэкспортом из бареля (обратная совместимость импортов); validate
  `npm run check:imports` (скрипт уже есть).
- **DoD:** tsc чисто; ни один импорт вне `services/api` не изменился.
- **Усилие:** S–M. **Риск:** низкий.

### E6. Декомпозиция ProjectDetail (follow-up, вне 6 недель)
- **Проблема:** 2196 строк, 44 useState, 30+ пропсов в ProjectDetailTabs
  (`ProjectDetailTabs.tsx:73-107`), включая сырые `set*`-сеттеры;
  `taskColumns` пересоздаётся каждый рендер (`ProjectDetail.tsx:1455`).
- **Шаги:** по одному табу: состояние таба → собственный хук/компонент;
  контракт табов — контекст вместо пропсов; `taskColumns` в useMemo.
- **DoD:** ProjectDetail < 800 строк; тесты хотя бы одного таба.
- **Усилие:** L. **Риск:** средний; только после E1 (кэш/загрузка уйдут в RQ).

---

## БД-схема (вне волн, по мере миграций)

- **F1 (в волне A5):** FK-индексы.
- **F2:** `String` без длины (~20 колонок: traceability.py, confluence.py:19-20,
  sprint.py:23,57,58,61, task.py:26-34, user.py:23). Для PostgreSQL безвредно
  (VARCHAR), для портируемости (MySQL) — задать длины. ВАЖНО: `ALTER` типа на
  больших таблицах берёт lock — выполнять только если появится требование
  портируемости. Приоритет низкий.

---

## Порядок и зависимости

```
A (дни 1-3)  ──► B1..B5 (нед. 1-2) ──► C1..C3 (нед. 2-3)
                         │
                         └──► D3, D4 (нед. 3-4)
D1, D2 (нед. 3-5) — параллельно с C, по модулю на PR
E2, E3, E5 (нед. 4) ──► E1 (нед. 4-5) ──► E4 RFC ──► E6 (follow-up)
```

Жёсткие зависимости: B1 ← `ENCRYPTION_SECRET` в deployment; B3/C3 ← Redis-стенд;
E4 ← E1; E6 ← E1; D2 — постепенно, не блокирует ничего.

## Метрики успеха (общие)

- `pytest` ≥ текущих 528 + новые тесты каждого пункта, ruff/mypy/tsc чистые.
- Счётчик SQL-запросов на list-эндпоинтах traceability (benchmark-скрипт) —
  кратен константе, не размеру выборки.
- CI: `check_silent_excepts.py` с non-regression baseline.
- В БД нет plaintext MFA-секретов (интеграционный тест-инспектор).

## Риски и способы их контроля

- **B1 (MFA-миграция):** добавить kill-switch `MFA_ENCRYPTION_ENABLED` на один
  релиз; e2e MFA-флоу обязателен.
- **D2 (транзакции):** маленькие PR, каждый — с тестом на rollback; запрет
  смешения стилей в одном файле.
- **E1 (React Query):** по странице за PR; сохранение старого пути до полной
  миграции запрещено (иначе — три системы кэширования).
