# Research: AI RAG-Based Document Evaluation & QnA Platform

**Branch**: `001-ai-rag-eval-platform` | **Phase**: 0 (Research) | **Date**: 2025-11-13

## Overview

This document consolidates research findings to resolve all "NEEDS CLARIFICATION" items from the Technical Context and provides best practices for technology choices.

---

## 1. Google Gemini API Integration

### Decision: Use Google Gemini API for LLM capabilities

**Rationale**:
- Native File Search Tool integration (formerly known as "Search and Grounding")
- Two-tier model strategy: `gemini-2.0-flash-exp` for QnA (speed), `gemini-2.0-flash-thinking-exp` for evaluation (quality)
- Official Python SDK: `google-generativeai`
- Built-in safety settings and content filtering
- Competitive pricing for educational use cases

**Best Practices**:
- Use context caching for system prompts to reduce costs
- Implement exponential backoff for rate limiting
- Set appropriate safety settings for educational content
- Store API key in environment variable, never in code
- Log all API calls for debugging and cost tracking

**Implementation Pattern**:
```python
import google.generativeai as genai

genai.configure(api_key=os.environ["GOOGLE_API_KEY"])

# QnA model configuration
qna_model = genai.GenerativeModel(
    model_name="gemini-2.0-flash-exp",
    tools=[{"file_search": {...}}]
)

# Evaluation model configuration
eval_model = genai.GenerativeModel(
    model_name="gemini-2.0-flash-thinking-exp",
    tools=[{"file_search": {...}}]
)
```

**Alternatives Considered**:
- OpenAI GPT-4: Excellent quality but higher cost, separate vector DB needed
- Anthropic Claude: Strong reasoning but no native RAG tool
- Local LLM (Llama): Lower latency but requires significant GPU resources

**References**:
- [Gemini API Documentation](https://ai.google.dev/gemini-api/docs)
- [File Search Tool Guide](https://ai.google.dev/gemini-api/docs/file-search)

---

## 2. Google File Search Tool (RAG Implementation)

### Decision: Use Google File Search Tool for document indexing and retrieval

**Rationale**:
- Managed vector store (no separate vector DB to maintain)
- Native integration with Gemini API
- Built-in PDF parsing and chunking
- Metadata filtering for user isolation (`user_id`, `random_key`)
- Automatic re-ranking of search results

**Best Practices**:
- Create two separate File Search Stores:
  - `main-store`: User-uploaded documents (A documents)
  - `rubric-store`: Evaluation criteria documents (B documents)
- Always include metadata on file upload:
  ```python
  metadata = {
      "user_id": str(user.id),
      "random_key": document.random_key,
      "document_type": "user_document"  # or "rubric"
  }
  ```
- Use metadata filters in every search query to ensure data isolation
- Store File Search Store references in SQLite for lifecycle management
- Implement cleanup jobs to remove documents from stores when deleted

**File Search Store Configuration**:
```python
# Create store
store = genai.create_file_search_store(
    name="main-store",
    config={
        "embedding_config": {
            "model": "models/text-embedding-004"
        }
    }
)

# Upload file with metadata
file = genai.upload_file(
    path=pdf_path,
    display_name=document.title,
    metadata={
        "user_id": str(user.id),
        "random_key": document.random_key
    }
)

# Add to store
genai.add_file_to_store(store_id=store.id, file_id=file.id)

# Query with metadata filter
response = model.generate_content(
    contents=[question],
    tools=[{
        "file_search": {
            "store_id": store.id,
            "metadata_filter": f'user_id="{user.id}" AND random_key="{doc.random_key}"'
        }
    }]
)
```

**Alternatives Considered**:
- Pinecone: Excellent performance but separate service, additional cost
- Weaviate: Open-source flexibility but requires self-hosting
- ChromaDB: Lightweight but limited scale, no managed service
- PostgreSQL pgvector: Cost-effective but requires manual chunking/embedding

**References**:
- [File Search Tool Documentation](https://ai.google.dev/gemini-api/docs/file-search)
- [Metadata Filtering Guide](https://ai.google.dev/gemini-api/docs/file-search#metadata-filtering)

---

## 3. FastAPI Best Practices for Educational Platform

### Decision: FastAPI with async/await for API routes

**Rationale**:
- High performance with async I/O for LLM API calls
- Built-in OpenAPI documentation generation
- Pydantic for request/response validation
- Easy integration with Jinja2 for SSR
- Excellent developer experience with type hints

**Best Practices**:
- **Router Organization**: Split by domain (auth, user_docs, qna, eval, admin)
- **Dependency Injection**: Use FastAPI dependencies for DB sessions, current user
- **Error Handling**: Custom exception handlers for user-friendly messages
- **Request Validation**: Pydantic schemas for all inputs/outputs
- **Session Management**: Use secure session cookies or JWT tokens
- **CORS Configuration**: Restrict origins in production
- **Rate Limiting**: Implement per-user rate limits for LLM calls

**File Upload Handling**:
```python
from fastapi import UploadFile, File, HTTPException

@router.post("/docs/upload")
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Validate file type
    if file.content_type != "application/pdf":
        raise HTTPException(400, "Only PDF files allowed")

    # Validate file size (50MB limit)
    contents = await file.read()
    if len(contents) > 50 * 1024 * 1024:
        raise HTTPException(400, "File size exceeds 50MB limit")

    # Save and process
    # ...
```

**Async LLM Call Pattern**:
```python
import httpx

async def call_gemini_api(prompt: str, model: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://generativelanguage.googleapis.com/v1/models/{model}:generateContent",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"contents": [{"parts": [{"text": prompt}]}]}
        )
        return response.json()
```

**Security Headers**:
```python
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.cors import CORSMiddleware

app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**References**:
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [Async Best Practices](https://fastapi.tiangolo.com/async/)

---

## 4. SQLite3 Configuration for Production Use

### Decision: SQLite3 with WAL mode and proper connection settings

**Rationale**:
- File-based simplicity for single-server deployment
- Zero configuration, no separate database server
- ACID compliance with proper settings
- WAL mode enables concurrent readers and single writer
- Sufficient for estimated scale (<1000 users, <10K documents)

**Best Practices**:
- **WAL Mode**: Enable Write-Ahead Logging for better concurrency
  ```sql
  PRAGMA journal_mode = WAL;
  ```
- **Foreign Keys**: Always enable foreign key constraints
  ```sql
  PRAGMA foreign_keys = ON;
  ```
- **Busy Timeout**: Set reasonable timeout for lock contention
  ```python
  connection.execute("PRAGMA busy_timeout = 5000")  # 5 seconds
  ```
- **Connection Pooling**: Use single connection pool with reasonable size
- **Backup Strategy**: Regular backups with `.backup()` command or file copy during WAL checkpoint
- **Index Optimization**: Create indexes on foreign keys and frequent query columns

**SQLAlchemy Configuration** (if using ORM):
```python
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()

engine = create_engine(
    "sqlite:///./data/app.db",
    connect_args={"check_same_thread": False},
    echo=settings.DEBUG
)
```

**Migration to PostgreSQL Path** (future consideration):
- Use SQLAlchemy ORM to abstract database operations
- Avoid SQLite-specific features in queries
- When scale requires, switch to PostgreSQL with minimal code changes

**Alternatives Considered**:
- PostgreSQL: Better concurrency but overkill for initial scale, requires separate server
- MySQL: Similar to PostgreSQL but less suitable for analytical queries
- MongoDB: NoSQL flexibility but poor fit for relational data (users, documents, evaluations)

**References**:
- [SQLite WAL Mode](https://www.sqlite.org/wal.html)
- [SQLite Best Practices](https://www.sqlite.org/np1queryprob.html)
- [SQLAlchemy with SQLite](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html)

---

## 5. Testing Strategy for AI-Powered Applications

### Decision: Three-tier testing with LLM response mocking

**Rationale**:
- Unit tests for business logic with mocked LLM responses
- Contract tests for API endpoints with schema validation
- Integration tests for full user journeys with test File Search Store

**Best Practices**:

#### Unit Testing
- Mock Gemini API responses using `pytest-mock` or `unittest.mock`
- Test business logic separately from external API calls
- Use fixtures for common test data (users, documents, prompts)

```python
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_qna_service_returns_answer(mock_gemini_api):
    # Given
    mock_gemini_api.return_value = {
        "candidates": [{"content": {"parts": [{"text": "Answer"}]}}]
    }

    # When
    with patch('app.services.qna_service.genai.GenerativeModel') as mock:
        mock.return_value.generate_content = mock_gemini_api
        result = await qna_service.ask_question(doc_id, question)

    # Then
    assert result == "Answer"
    mock_gemini_api.assert_called_once()
```

#### Contract Testing
- Validate OpenAPI schema compliance
- Test all endpoints for expected status codes and response structure
- Use `httpx.AsyncClient` for FastAPI testing

```python
from httpx import AsyncClient
from app.main import app

@pytest.mark.asyncio
async def test_upload_document_contract():
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Given
        files = {"file": ("test.pdf", pdf_content, "application/pdf")}
        data = {"title": "Test Document"}

        # When
        response = await client.post(
            "/docs/upload",
            files=files,
            data=data,
            cookies={"session": auth_cookie}
        )

        # Then
        assert response.status_code == 200
        assert "document_id" in response.json()
        assert response.json()["status"] == "uploaded"
```

#### Integration Testing
- Use separate test database and test File Search Store
- Test complete user journeys from upload to QnA to evaluation
- Verify data isolation between test users

```python
@pytest.mark.integration
async def test_complete_qna_flow():
    # Setup: Create test user, test store
    user = await create_test_user()
    store = await create_test_file_search_store()

    # Upload document
    doc = await upload_test_document(user, "test.pdf")

    # Wait for indexing (or mock)
    await wait_for_document_ready(doc.id)

    # Ask question
    answer = await ask_question(doc.id, "What is the main topic?")

    # Verify
    assert answer is not None
    assert len(answer) > 0

    # Cleanup
    await cleanup_test_data(user, doc, store)
```

**Test Data Management**:
- Use pytest fixtures for test users, documents, and prompts
- Create factory functions for generating test data
- Implement proper cleanup in teardown to avoid test pollution

**CI/CD Integration**:
- Run unit tests on every commit (fast, no external dependencies)
- Run contract tests on PR creation
- Run integration tests nightly or before deployment (slow, requires API keys)

**References**:
- [pytest Documentation](https://docs.pytest.org/)
- [FastAPI Testing Guide](https://fastapi.tiangolo.com/tutorial/testing/)
- [Testing AI Applications](https://www.anthropic.com/index/testing-ai-applications)

---

## 6. User Authentication and Session Management

### Decision: Session-based authentication with secure cookies

**Rationale**:
- Simple implementation for server-side rendered application
- FastAPI SessionMiddleware provides built-in support
- CSRF protection easier with session cookies
- Suitable for single-server deployment

**Best Practices**:
- **Password Hashing**: Use bcrypt or argon2 for password storage
  ```python
  from passlib.context import CryptContext

  pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
  hashed_password = pwd_context.hash(plain_password)
  verified = pwd_context.verify(plain_password, hashed_password)
  ```
- **Session Configuration**:
  ```python
  app.add_middleware(
      SessionMiddleware,
      secret_key=settings.SECRET_KEY,
      session_cookie="session",
      max_age=3600 * 24 * 7,  # 7 days
      same_site="lax",
      https_only=settings.PRODUCTION,
  )
  ```
- **Current User Dependency**:
  ```python
  async def get_current_user(
      request: Request,
      db: Session = Depends(get_db)
  ) -> User:
      user_id = request.session.get("user_id")
      if not user_id:
          raise HTTPException(401, "Not authenticated")

      user = db.query(User).filter(User.id == user_id).first()
      if not user:
          raise HTTPException(401, "User not found")

      return user
  ```

**Admin Role Separation**:
- Store admin flag in User model or create separate Admin table
- Use role-based dependency for admin routes:
  ```python
  async def get_current_admin(
      current_user: User = Depends(get_current_user)
  ) -> User:
      if not current_user.is_admin:
          raise HTTPException(403, "Admin access required")
      return current_user
  ```

**CSRF Protection**:
- Generate CSRF token on form render
- Validate token on form submission
- Use FastAPI CSRF middleware or manual implementation

**Alternatives Considered**:
- JWT Tokens: More suitable for SPA or mobile apps, adds complexity for SSR
- OAuth2: Future enhancement for third-party login (Google, GitHub)

**References**:
- [FastAPI Security Tutorial](https://fastapi.tiangolo.com/tutorial/security/first-steps/)
- [passlib Documentation](https://passlib.readthedocs.io/)

---

## 7. Frontend Architecture with Jinja2 and Tailwind CSS

### Decision: Server-side rendering with Jinja2 + Tailwind CSS via CDN

**Rationale**:
- Simplicity: No separate frontend build process
- Performance: CDN delivery for Tailwind CSS
- SEO-friendly: Full HTML rendering on server
- Progressive enhancement: Add JavaScript only where needed

**Best Practices**:

#### Jinja2 Template Organization
```
templates/
├── base.html           # Common layout, Tailwind CDN, nav
├── user/
│   ├── dashboard.html  # Extends base, shows document list
│   └── doc_detail.html # Extends base, QnA and evaluation UI
└── admin/
    ├── admin_dashboard.html  # Admin metrics
    ├── admin_users.html      # User management
    ├── admin_user_detail.html
    ├── admin_qna_logs.html
    └── admin_prompts.html
```

#### Base Template Pattern
```html
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}AI Document Platform{% endblock %}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    {% block head %}{% endblock %}
</head>
<body class="bg-gray-50">
    {% include 'partials/nav.html' %}

    <main class="container mx-auto px-4 py-8">
        {% block content %}{% endblock %}
    </main>

    <script src="{{ url_for('static', path='/js/app.js') }}"></script>
    {% block scripts %}{% endblock %}
</body>
</html>
```

#### HTMX for Dynamic Updates (Optional Enhancement)
- Use HTMX for QnA without page reload
- Progressive enhancement: works without JavaScript
```html
<form hx-post="/qna/{{ doc.id }}" hx-target="#answer-area">
    <input name="question" type="text" required>
    <button type="submit">Ask Question</button>
</form>
<div id="answer-area"></div>
```

#### Tailwind CSS Configuration
- Start with CDN for rapid development
- Transition to build process when custom theme needed:
  ```bash
  npm install -D tailwindcss
  npx tailwindcss init
  ```

**Accessibility Standards**:
- Use semantic HTML elements
- Include ARIA labels for interactive elements
- Ensure keyboard navigation works
- Maintain color contrast ratios (WCAG AA)

**Alternatives Considered**:
- React SPA: Better interactivity but adds build complexity
- Vue.js: Similar to React, overkill for current requirements
- Alpine.js: Lighter than React/Vue, good middle ground for future

**References**:
- [Jinja2 Documentation](https://jinja.palletsprojects.com/)
- [Tailwind CSS Documentation](https://tailwindcss.com/docs)
- [HTMX Documentation](https://htmx.org/docs/)

---

## 8. Error Handling and Logging Strategy

### Decision: Structured logging with Python logging module + error tracking

**Rationale**:
- Python logging module is sufficient for single-server deployment
- Structured logging enables easier debugging and monitoring
- Separate log levels for different concerns

**Best Practices**:

#### Logging Configuration
```python
import logging
from pythonjsonlogger import jsonlogger

# Configure JSON structured logging
logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter(
    '%(asctime)s %(name)s %(levelname)s %(message)s'
)
logHandler.setFormatter(formatter)

logger = logging.getLogger(__name__)
logger.addHandler(logHandler)
logger.setLevel(logging.INFO)
```

#### Log Categories
- **app**: General application logs
- **api**: API request/response logs
- **llm**: LLM API calls, costs, latency
- **db**: Database queries, performance
- **security**: Authentication, authorization events

#### LLM Call Logging
```python
async def call_gemini_with_logging(prompt: str, model: str):
    logger.info("LLM call started", extra={
        "model": model,
        "prompt_length": len(prompt),
        "user_id": current_user.id
    })

    start_time = time.time()
    try:
        response = await gemini_api.generate(prompt)
        latency = time.time() - start_time

        logger.info("LLM call succeeded", extra={
            "model": model,
            "latency_ms": int(latency * 1000),
            "response_length": len(response.text),
            "tokens_used": response.usage.total_tokens
        })

        return response
    except Exception as e:
        logger.error("LLM call failed", extra={
            "model": model,
            "error": str(e),
            "latency_ms": int((time.time() - start_time) * 1000)
        })
        raise
```

#### Error Handling Patterns
```python
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.warning("HTTP exception", extra={
        "status_code": exc.status_code,
        "detail": exc.detail,
        "path": request.url.path
    })
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception", extra={
        "error": str(exc),
        "path": request.url.path
    }, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )
```

**Monitoring and Alerting** (Future Enhancement):
- Integrate with Sentry or similar for error tracking
- Set up CloudWatch or equivalent for log aggregation
- Configure alerts for high error rates or slow response times

**References**:
- [Python Logging Cookbook](https://docs.python.org/3/howto/logging-cookbook.html)
- [Structured Logging Best Practices](https://www.structlog.org/)

---

## 9. Deployment and Environment Configuration

### Decision: uv-based dependency management + environment variables

**Rationale**:
- uv provides fast, reliable Python package management
- Environment variables for configuration follows 12-factor app principles
- Easy transition from development to production

**Best Practices**:

#### pyproject.toml Configuration
```toml
[project]
name = "elp-gemini"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",
    "jinja2>=3.1.3",
    "httpx>=0.26.0",
    "pydantic>=2.5.0",
    "python-multipart>=0.0.6",
    "google-generativeai>=0.3.0",
    "sqlalchemy>=2.0.25",
    "aiosqlite>=0.19.0",
    "passlib[bcrypt]>=1.7.4",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.21.0",
    "pytest-mock>=3.12.0",
    "black>=24.0.0",
    "ruff>=0.1.0",
    "mypy>=1.8.0",
]

[tool.black]
line-length = 80
target-version = ['py310']

[tool.ruff]
line-length = 80
select = ["E", "F", "I", "N", "W"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

#### Environment Variable Configuration
```python
# app/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Application
    DEBUG: bool = False
    SECRET_KEY: str
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    # Database
    DATABASE_URL: str = "sqlite:///./data/app.db"

    # Google Gemini API
    GOOGLE_API_KEY: str
    GEMINI_QNA_MODEL: str = "gemini-2.0-flash-exp"
    GEMINI_EVAL_MODEL: str = "gemini-2.0-flash-thinking-exp"

    # File Search
    FS_MAIN_STORE_NAME: str = "main-store"
    FS_RUBRIC_STORE_NAME: str = "rubric-store"

    # File Upload
    MAX_UPLOAD_SIZE: int = 50 * 1024 * 1024  # 50MB
    UPLOAD_DIR: str = "./data/uploads"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
```

#### .env.example
```bash
# Application
DEBUG=False
SECRET_KEY=your-secret-key-here-min-32-chars
ALLOWED_ORIGINS=["http://localhost:3000"]

# Google API
GOOGLE_API_KEY=your-google-api-key-here

# Database
DATABASE_URL=sqlite:///./data/app.db

# Optional: Override model names
# GEMINI_QNA_MODEL=gemini-2.0-flash-exp
# GEMINI_EVAL_MODEL=gemini-2.0-flash-thinking-exp
```

#### Startup Commands
```bash
# Development
uv venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows
uv pip install -e ".[dev]"
uv run uvicorn app.main:app --reload

# Production
uv pip install .
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

**Docker Deployment** (Optional):
```dockerfile
FROM python:3.10-slim

WORKDIR /app

COPY pyproject.toml ./
RUN pip install uv && uv pip install --system .

COPY app ./app
COPY data ./data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**References**:
- [uv Documentation](https://github.com/astral-sh/uv)
- [12-Factor App](https://12factor.net/)
- [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)

---

## Summary

All "NEEDS CLARIFICATION" items from Technical Context have been resolved:

✅ **Language/Version**: Python 3.10+ confirmed
✅ **Primary Dependencies**: FastAPI, Jinja2, SQLite3, Google Gemini API, httpx, pydantic validated
✅ **Storage**: SQLite3 with WAL mode + Google File Search Store for vectors
✅ **Testing**: pytest with async support, contract and integration test strategy defined
✅ **Performance Goals**: Targets clarified with implementation patterns
✅ **Constraints**: File size, isolation, and latency requirements documented
✅ **Scale/Scope**: Small-to-medium scale validated as appropriate for tech choices

**Next Steps**: Proceed to Phase 1 (Design & Contracts) with confidence that all technology choices are validated and best practices documented.
