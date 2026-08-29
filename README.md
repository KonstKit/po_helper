# PO Helper - Product Owner Assistant

Comprehensive project management tool for Product Owners working with Jira and Confluence, providing analytics, forecasting, and risk management capabilities.

## рџљЂ Features

### Core Functionality
- **Jira Integration**: Seamless sync with Jira projects, issues, and sprints
- **Confluence Integration**: Link project documentation and requirements
- **Real-time Analytics**: Team velocity, burndown charts, and progress tracking
- **Risk Management**: Automated risk detection and early warning system
- **Forecasting**: Project completion predictions based on historical data
- **Excel Export**: Comprehensive reporting capabilities

### Analytics & Insights
- **Team Velocity**: Track and analyze sprint-over-sprint performance
- **Burndown Charts**: Visual progress tracking for sprints and projects
- **Resource Management**: Team capacity planning and workload analysis
- **Budget Tracking**: Cost analysis and budget efficiency monitoring
- **Technical Debt**: Quality metrics and code health monitoring

### Advanced Features
- **Role-Based Access Control (RBAC)**: User, Manager, and Admin roles with granular permissions
- **Artifact Traceability**: Link requirements, tasks, tests, and commits with confidence scoring
- **Background Tasks**: Celery-powered async Jira synchronization
- **Quality Analytics**: Code coverage tracking and quality gate monitoring

## рџЏ—пёЏ Architecture

```
po_helper/
в”њв”Ђв”Ђ backend/           # FastAPI Python backend
в”‚   в”њв”Ђв”Ђ app/
в”‚   в”‚   в”њв”Ђв”Ђ api/       # REST API endpoints
в”‚   в”‚   в”њв”Ђв”Ђ core/      # Configuration and utilities
в”‚   в”‚   в”њв”Ђв”Ђ models/    # Database models
в”‚   в”‚   в”њв”Ђв”Ђ schemas/   # Pydantic schemas
в”‚   в”‚   в””в”Ђв”Ђ services/  # Business logic
в”‚   в””в”Ђв”Ђ requirements.txt
в”њв”Ђв”Ђ frontend/          # React TypeScript frontend
в”‚   в”њв”Ђв”Ђ src/
в”‚   в”‚   в”њв”Ђв”Ђ components/
в”‚   в”‚   в”њв”Ђв”Ђ pages/
в”‚   в”‚   в”њв”Ђв”Ђ services/
в”‚   в”‚   в””в”Ђв”Ђ store/
в”‚   в””в”Ђв”Ђ package.json
в”њв”Ђв”Ђ docker/           # Docker configuration
в””в”Ђв”Ђ docs/            # Documentation
```

## рџ› пёЏ Technology Stack

### Backend
- **FastAPI** - High-performance Python web framework
- **SQLAlchemy** - Database ORM with async support
- **PostgreSQL** - Primary database
- **Redis** - Caching and background tasks
- **Celery** - Distributed task queue
- **Alembic** - Database migrations

### Frontend
- **React 18** - UI framework
- **TypeScript** - Type-safe JavaScript
- **Material-UI** - Component library
- **Redux Toolkit** - State management
- **React Query** - Server state management
- **Chart.js** - Data visualization

### Infrastructure
- **Docker & Docker Compose** - Containerization
- **Nginx** - Reverse proxy and static files
- **GitHub Actions** - CI/CD pipeline

## рџљЂ Quick Start

### Prerequisites
- Docker and Docker Compose
- Node.js 18+ (for local development)
- Python 3.11+ (for local development)

### 1. Clone Repository
```bash
git clone https://github.com/yourorg/po_helper.git
cd po_helper
```

### 2. Environment Setup
```bash
# Copy environment template
cp .env.example .env

# Edit .env with your Jira/Confluence credentials
nano .env
```

For a single-user local demo, keep `BACKEND_BIND_HOST=127.0.0.1`, keep `ALLOW_UNAUTHENTICATED_DEMO_API=false`, and set a dedicated `ENCRYPTION_SECRET` for persisted Jira/Confluence tokens.

### 3. Run with Docker
```bash
# Start all services
docker-compose -f docker-compose.dev.yml up -d

# View logs
docker-compose -f docker-compose.dev.yml logs -f
```

For the strict localhost demo, `docker-compose.dev.yml` runs the backend with host networking so `uvicorn` still binds `127.0.0.1`. If host networking is unavailable in your Docker Desktop setup, run the backend locally with the provided start scripts instead of the Docker demo path.

**Known limitation — proxied frontend → backend path:** because the backend is bound to the host loopback inside `network_mode: host`, the bridge-networked frontend container cannot reach it through nginx (`/api/*` and `/api/v1/ws` will 502). This is intentional for the security boundary; for the documented dev/demo flow prefer running the backend on the host (see *Backend Development* below) and loading `http://localhost:3001`. The header of `docker-compose.dev.yml` lists the two alternative escape hatches if you need a Docker-only path.

### 4. Access Application
- **Frontend**: http://localhost:3001 (Vite dev) / http://localhost:3000 (docker nginx)
- **Backend API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs

## рџ“‹ Configuration

### Jira Setup
1. Go to Jira Account Settings
2. Create API Token: Security в†’ Create API Token
3. Add credentials to `.env`:
```env
JIRA_BASE_URL=https://yourcompany.atlassian.net
JIRA_EMAIL=your-email@company.com
JIRA_API_TOKEN=your-api-token
```

### Jira HTTP Tuning and Circuit Breaker
Add these to `.env` as needed:

```env
# HTTP timeouts and retries for Jira requests
JIRA_HTTP_TIMEOUT=60                 # seconds (default 60)
JIRA_WORKLOG_TIMEOUT=120            # seconds for worklog endpoints (default 120)
JIRA_HTTP_MAX_RETRIES=2              # retries on Read/Connect timeout (default 2)
JIRA_HTTP_BACKOFF_SECONDS=1.0        # base backoff for retries (default 1.0)

# Optional circuit breaker (prevents request loops during outages)
JIRA_CB_ENABLED=false                # enable CB (default false)
JIRA_CB_THRESHOLD=5                  # consecutive failures before open (default 5)
JIRA_CB_SLEEP_SECONDS=60             # hold-open duration in seconds (default 60)
```

Metrics are exposed at `/api/v1/health/metrics` (Prometheus format). Counters include `jira_cb_open_total`,
and gauges include `jira_cb_open` and `jira_cb_sleep_seconds`.

### Confluence Setup (Optional)
```env
CONFLUENCE_BASE_URL=https://yourcompany.atlassian.net/wiki
CONFLUENCE_EMAIL=your-email@company.com
CONFLUENCE_API_TOKEN=your-api-token
```

## рџ”§ Development

### Backend Development
```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\\Scripts\\activate

# Install dependencies
pip install -r requirements.txt

# Run development server
BACKEND_BIND_HOST=127.0.0.1 uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Frontend Development
```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

If you need frontend-specific local overrides, copy `frontend/.env.example` to `frontend/.env` and keep `VITE_ALLOW_UNAUTHENTICATED_DEMO_API=false` unless you are intentionally running a strict localhost-only demo.

### Frontend Typecheck/Tests in Docker (no local Node/npm)
If you don't have `node`/`npm` available on the host, you can run frontend checks inside Docker.

```bash
# Start the tooling container once (installs deps into a named volume)
docker compose -f docker-compose.pohelper.deploy.yml --profile tools up -d frontend-tooling

# Run checks
docker compose -f docker-compose.pohelper.deploy.yml --profile tools exec frontend-tooling npm run typecheck
docker compose -f docker-compose.pohelper.deploy.yml --profile tools exec frontend-tooling npm test -- --run
```

### Database Migrations
```bash
# Create migration
alembic revision --autogenerate -m "Description"

# Apply migrations
alembic upgrade head
```

## рџ“Љ Usage Examples

### 1. Project Setup
```python
# Create new project
POST /api/v1/projects/
{
    "name": "E-commerce Platform",
    "jira_key": "ECOM",
    "description": "Main e-commerce application"
}
```

### 2. Sync Jira Data
```bash
# Sync project data
curl -X POST -H "Authorization: Bearer <token>" "http://localhost:8000/api/v1/jira/projects/ECOM/sync"
```

### 3. Get Analytics
```bash
# Get team velocity
curl "http://localhost:8000/api/v1/analytics/projects/1/velocity"

# Get risk assessment
curl "http://localhost:8000/api/v1/analytics/projects/1/risks"
```

## рџ“€ Key Metrics

The application tracks and visualizes:

- **Velocity Trends**: Story points completed per sprint
- **Completion Rates**: Task completion efficiency
- **Budget Utilization**: Spend vs. planned budget
- **Risk Indicators**: Overdue tasks, blockers, scope changes
- **Team Performance**: Individual and team productivity metrics
- **Quality Metrics**: Bug rates, technical debt, code coverage

## рџ”’ Security

- JWT-based authentication
- Local demo defaults bind the backend to `127.0.0.1` and keep Jira/Confluence sync behind login
- `ALLOW_UNAUTHENTICATED_DEMO_API` is demo-only and must stay disabled outside strict localhost usage
- Persisted Jira/Confluence tokens require a dedicated `ENCRYPTION_SECRET`
- API rate limiting
- SQL injection protection
- XSS prevention
- CORS configuration
- Environment-based secrets

## рџљЂ Deployment

### Production Deployment
```bash
# Build production images
docker-compose -f docker-compose.prod.yml build

# Deploy with production settings
docker-compose -f docker-compose.prod.yml up -d
```

### Environment Variables
See `.env.example` for all required environment variables.

## рџ§Є Testing

### Backend Tests
```bash
cd backend
pytest tests/ -v --cov=app
```

### Frontend Tests
```bash
cd frontend
npm test
```

## рџ“љ API Documentation

Full API documentation is available at `/docs` when the server is running.

### Key Endpoints
- **Projects**: `/api/v1/projects/`
- **Tasks**: `/api/v1/tasks/`
- **Analytics**: `/api/v1/analytics/`
- **Jira Integration**: `/api/v1/jira/`

## рџ¤ќ Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature/amazing-feature`
3. Commit changes: `git commit -m 'Add amazing feature'`
4. Push to branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

## рџ“ќ License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## рџ† Support

- **Documentation**: [Wiki](https://github.com/yourorg/po_helper/wiki)
- **Issues**: [GitHub Issues](https://github.com/yourorg/po_helper/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourorg/po_helper/discussions)

## рџ—єпёЏ Roadmap

### Version 1.1
- [ ] GitLab integration (API client beyond webhooks)
- [ ] Real-time notifications
- [ ] Mobile responsive design
- [ ] Advanced reporting exports

### Version 1.2
- [ ] Multi-tenant support with RLS
- [ ] Custom dashboard widgets
- [ ] Advanced forecasting models
- [ ] Streaming ETL pipelines

## рџ“Љ Screenshots

### Dashboard
![Dashboard](docs/images/dashboard.png)

### Project Analytics
![Analytics](docs/images/analytics.png)

### Risk Management
![Risks](docs/images/risks.png)

---

**Built with вќ¤пёЏ for Product Owners who want to make data-driven decisions**

## Documentation
- [Deployment Guide](docs/DEPLOYMENT.md)
- [Release Notes](docs/RELEASE_NOTES.md)
- [Testing Guide](docs/TESTING.md)
