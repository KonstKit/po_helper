# План исправления проблем PO Helper

## Приоритет 1: Критические исправления безопасности (День 1)

### 1.1 Исправить SECRET_KEY
```bash
# backend/app/core/config.py
```
```python
import secrets

class Settings(BaseSettings):
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    # Или через переменную окружения
    # SECRET_KEY: str = Field(..., env='SECRET_KEY')
```

**Действия:**
1. Сгенерировать новый SECRET_KEY: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
2. Добавить в .env: `SECRET_KEY=<generated_key>`
3. Обновить config.py для чтения из env
4. Перезапустить backend

### 1.2 Добавить Rate Limiting
```bash
pip install slowapi
```

```python
# backend/app/core/rate_limit.py
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100/minute"]
)

# backend/app/main.py
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# На критических endpoints:
@router.post("/auth/login")
@limiter.limit("5/minute")
async def login(...):
    ...
```

## Приоритет 2: Исправление Jira интеграции (День 1-2)

### 2.1 Исправить Jira API ошибку
```python
# backend/app/services/jira_service.py

def _handle_response(self, response: requests.Response) -> dict:
    """Обработка ответа с проверкой content-type"""
    if response.status_code == 401:
        raise JiraAuthError("Authentication failed")

    content_type = response.headers.get('content-type', '')

    if 'application/json' not in content_type:
        # Логируем HTML ответ для диагностики
        logger.error(f"Non-JSON response from Jira: {content_type}")
        logger.debug(f"Response body: {response.text[:500]}")

        # Проверяем, не редирект ли это на логин
        if response.status_code == 302 or 'login' in response.url:
            raise JiraAuthError("Jira requires re-authentication")

        raise JiraUnexpectedResponse(f"Expected JSON, got {content_type}")

    return response.json()
```

### 2.2 Добавить логирование при старте
```python
# backend/app/main.py

@app.on_event("startup")
async def startup_event():
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await _ensure_sqlite_columns()
        logger.info("Database tables created/verified successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        # Не блокируем запуск, но логируем

    # Инициализация сервисов с логированием
    try:
        # ... existing code ...
    except Exception as e:
        logger.error(f"Service initialization failed: {e}")
```

## Приоритет 3: Оптимизация производительности (Неделя 1)

### 3.1 Frontend Code Splitting
```typescript
// frontend/src/App.tsx
import { lazy, Suspense } from 'react';

// Lazy load тяжёлых компонентов
const Analytics = lazy(() => import('./pages/Analytics'));
const ProjectDetail = lazy(() => import('./pages/ProjectDetail'));
const ConfluenceViewer = lazy(() => import('./pages/ConfluenceViewer'));

// В роутинге:
<Suspense fallback={<Loading />}>
  <Routes>
    <Route path="/analytics" element={<Analytics />} />
    <Route path="/projects/:id" element={<ProjectDetail />} />
    <Route path="/confluence" element={<ConfluenceViewer />} />
  </Routes>
</Suspense>
```

```javascript
// frontend/vite.config.ts
export default defineConfig({
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          'vendor-mui': ['@mui/material', '@mui/icons-material'],
          'vendor-charts': ['chart.js', 'react-chartjs-2', 'recharts'],
          'vendor-utils': ['axios', 'date-fns', '@tanstack/react-query']
        }
      }
    }
  }
});
```

### 3.2 Добавить индексы в БД
```python
# backend/alembic/versions/xxx_add_performance_indexes.py
def upgrade():
    # Индексы для tasks
    op.create_index('ix_tasks_project_id', 'tasks', ['project_id'])
    op.create_index('ix_tasks_assignee_name', 'tasks', ['assignee_name'])
    op.create_index('ix_tasks_status', 'tasks', ['status'])
    op.create_index('ix_tasks_sprint_id', 'tasks', ['sprint_id'])

    # Индексы для sprints
    op.create_index('ix_sprints_project_id', 'sprints', ['project_id'])
    op.create_index('ix_sprints_start_date', 'sprints', ['start_date'])

    # Индексы для pull_requests
    op.create_index('ix_pull_requests_project_id', 'pull_requests', ['project_id'])
    op.create_index('ix_pull_requests_state', 'pull_requests', ['state'])
    op.create_index('ix_pull_requests_opened_at', 'pull_requests', ['opened_at'])
```

## Приоритет 4: Исправление архитектурных проблем (Неделя 1-2)

### 4.1 Миграция на SQLAlchemy 2.0
```python
# backend/app/core/database.py
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

class Base(DeclarativeBase):
    pass

engine = create_async_engine(settings.DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)
```

### 4.2 Docker окружение
```yaml
# docker-compose.local.yml
version: '3.8'
services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: po_helper
      POSTGRES_PASSWORD: po_helper_pass
      POSTGRES_DB: po_helper
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  postgres_data:
```

## Приоритет 5: Улучшение конфигурации (Неделя 1)

### 5.1 Полный .env.example
```bash
# backend/.env.example

# Security
SECRET_KEY=generate-with-secrets.token_urlsafe(32)
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/po_helper
# For development with SQLite:
# DATABASE_URL=sqlite+aiosqlite:///./po_helper.db

# Jira Integration
JIRA_BASE_URL=https://your-jira.atlassian.net
JIRA_EMAIL=your-email@example.com
JIRA_API_TOKEN=your-api-token
JIRA_FORCE_PAT=false

# Confluence Integration
CONFLUENCE_BASE_URL=https://your-wiki.atlassian.net
CONFLUENCE_EMAIL=your-email@example.com
CONFLUENCE_API_TOKEN=your-api-token

# GitHub Integration (optional)
GITHUB_API_TOKEN=ghp_xxxxxxxxxxxx
GITHUB_WEBHOOK_SECRET=your-webhook-secret

# Redis (for Celery)
REDIS_URL=redis://localhost:6379/0

# CORS
CORS_ORIGINS=["http://localhost:3000", "http://localhost:3001"]

# Feature Flags
ENABLE_CONFLUENCE_AUTOLINK=true
ENABLE_MATRIX_CACHE=true
DEBUG=false
```

### 5.2 Миграция на Pydantic v2 ConfigDict
```python
# backend/app/schemas/base.py
from pydantic import BaseModel, ConfigDict

class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

# Заменить во всех schemas:
# class Config:
#     orm_mode = True
# На:
# model_config = ConfigDict(from_attributes=True)
```

## Приоритет 6: Тестирование (Неделя 2)

### 6.1 Backend тесты
```python
# backend/tests/test_auth.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, test_user):
    response = await client.post(
        "/api/v1/auth/login",
        data={
            "username": test_user.email,
            "password": "testpass123"
        }
    )
    assert response.status_code == 200
    assert "access_token" in response.json()

# backend/tests/conftest.py
import pytest
from httpx import AsyncClient
from app.main import app

@pytest.fixture
async def client():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac
```

### 6.2 Frontend тесты
```typescript
// frontend/src/__tests__/api.test.ts
import { listProjects } from '../services/api';
import { vi } from 'vitest';

describe('API Service', () => {
  it('should fetch projects', async () => {
    const mockProjects = [{ id: 1, name: 'Test' }];
    vi.mock('axios', () => ({
      get: vi.fn(() => Promise.resolve({ data: mockProjects }))
    }));

    const projects = await listProjects();
    expect(projects).toEqual(mockProjects);
  });
});
```

## Команды для запуска после исправлений

```bash
# Backend
cd backend
pip install -r requirements.txt
alembic upgrade head
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Frontend
cd frontend
npm install
npm run dev

# Тесты
cd backend
pytest tests/ -v --cov=app

cd frontend
npm test
```

## Метрики успеха

После выполнения плана проверить:
1. ✅ SECRET_KEY изменён и читается из env
2. ✅ Rate limiting работает на /auth/login
3. ✅ Jira API возвращает корректные данные
4. ✅ Frontend bundle < 500KB после code splitting
5. ✅ Запросы к БД выполняются < 100ms
6. ✅ Все тесты проходят
7. ✅ Docker окружение запускается корректно