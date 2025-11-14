# Quickstart: AI RAG-Based Document Evaluation & QnA Platform

**Branch**: `001-ai-rag-eval-platform` | **Phase**: 1 (Design) | **Date**: 2025-11-13

## Overview

This guide provides step-by-step instructions for setting up, developing, and testing the platform. Follow the TDD workflow as mandated by the project constitution.

---

## Prerequisites

- **Python**: 3.10 or higher
- **uv**: Python package manager ([Install guide](https://github.com/astral-sh/uv))
- **Google Cloud Account**: For Gemini API access
- **Git**: For version control
- **Code Editor**: VS Code, PyCharm, or similar with Python support

---

## Initial Setup

### 1. Clone Repository and Create Branch

```bash
# Clone repository (if not already done)
cd /mnt/d/dev/elp_gemini

# Verify you're on the feature branch
git branch
# Should show: * 001-ai-rag-eval-platform
```

### 2. Create Python Virtual Environment

```bash
# Create virtual environment using uv
uv venv

# Activate virtual environment
# On Linux/Mac:
source .venv/bin/activate

# On Windows:
.venv\Scripts\activate
```

### 3. Install Dependencies

```bash
# Install project dependencies
uv pip install fastapi uvicorn[standard] jinja2 httpx pydantic \
    python-multipart google-generativeai sqlalchemy aiosqlite \
    passlib[bcrypt] python-dotenv

# Install development dependencies
uv pip install pytest pytest-asyncio pytest-mock black ruff mypy
```

### 4. Configure Environment Variables

```bash
# Create .env file
cat > .env << 'EOF'
# Application
DEBUG=True
SECRET_KEY=dev-secret-key-replace-in-production-min-32-chars
ALLOWED_ORIGINS=["http://localhost:3000"]

# Google Gemini API
GOOGLE_API_KEY=your-google-api-key-here

# Database
DATABASE_URL=sqlite:///./data/app.db

# File Search
FS_MAIN_STORE_NAME=main-store
FS_RUBRIC_STORE_NAME=rubric-store

# File Upload
MAX_UPLOAD_SIZE=52428800
UPLOAD_DIR=./data/uploads
EOF

# IMPORTANT: Get your Google API key from
# https://makersuite.google.com/app/apikey
# and replace 'your-google-api-key-here' in .env
```

### 5. Create Data Directories

```bash
# Create necessary directories
mkdir -p data/uploads
mkdir -p app/models app/routers app/services app/schemas
mkdir -p app/templates/user app/templates/admin app/static/css app/static/js
mkdir -p tests/unit tests/contract tests/integration
```

### 6. Configure Black Formatter

```bash
# Create pyproject.toml with formatting configuration
cat > pyproject.toml << 'EOF'
[project]
name = "elp-gemini"
version = "0.1.0"
requires-python = ">=3.10"

[tool.black]
line-length = 80
target-version = ['py310']

[tool.ruff]
line-length = 80
select = ["E", "F", "I", "N", "W"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
EOF
```

---

## Development Workflow (TDD Cycle)

### Phase 1: Red (Write Failing Test)

**Example: User Authentication**

```python
# tests/unit/test_auth.py
import pytest
from app.services.auth_service import AuthService
from app.models.users import User

@pytest.mark.asyncio
async def test_authenticate_user_with_valid_credentials():
    """
    Test: User can authenticate with correct email and password
    Expected: Returns user object
    """
    # Arrange
    email = "test@example.com"
    password = "SecurePass123"
    auth_service = AuthService()

    # Act
    user = await auth_service.authenticate(email, password)

    # Assert
    assert user is not None
    assert user.email == email
    assert user.is_admin is False
```

Run test to see it fail:
```bash
pytest tests/unit/test_auth.py -v
# Expected: ImportError or AttributeError (module doesn't exist yet)
```

### Phase 2: Green (Implement Minimum Code)

```python
# app/services/auth_service.py
from passlib.context import CryptContext
from app.models.users import User
from app.db import get_db

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class AuthService:
    async def authenticate(self, email: str, password: str):
        db = next(get_db())
        user = db.query(User).filter(User.email == email).first()

        if not user:
            return None

        if not pwd_context.verify(password, user.hashed_password):
            return None

        return user
```

Run test again:
```bash
pytest tests/unit/test_auth.py -v
# Expected: Test passes (GREEN)
```

### Phase 3: Refactor (Improve Code)

```python
# app/services/auth_service.py (refactored)
from typing import Optional
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from app.models.users import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class AuthService:
    def __init__(self, db: Session):
        self.db = db

    async def authenticate(
        self, email: str, password: str
    ) -> Optional[User]:
        """Authenticate user with email and password"""
        user = self._get_user_by_email(email)

        if not user or not self._verify_password(password, user):
            return None

        return user

    def _get_user_by_email(self, email: str) -> Optional[User]:
        return self.db.query(User).filter(
            User.email == email
        ).first()

    def _verify_password(
        self, plain_password: str, user: User
    ) -> bool:
        return pwd_context.verify(
            plain_password, user.hashed_password
        )
```

Run test to ensure refactoring didn't break anything:
```bash
pytest tests/unit/test_auth.py -v
# Expected: Test still passes
```

---

## Running the Application

### 1. Initialize Database

```python
# Create app/db.py first
# Then run database initialization

python -c "
from app.db import init_db
init_db()
print('Database initialized successfully')
"
```

### 2. Start Development Server

```bash
# Start FastAPI with auto-reload
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Server will be available at:
# http://localhost:8000
# API docs at: http://localhost:8000/docs
```

### 3. Test Endpoints

```bash
# Health check (if implemented)
curl http://localhost:8000/

# Login endpoint
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "admin_password"}'
```

---

## Testing Strategy

### Unit Tests (Fast, No External Dependencies)

```bash
# Run all unit tests
pytest tests/unit/ -v

# Run specific test file
pytest tests/unit/test_auth.py -v

# Run with coverage
pytest tests/unit/ --cov=app --cov-report=html
```

**Test Structure**:
- `tests/unit/test_auth.py`: Authentication service tests
- `tests/unit/test_file_search_service.py`: File Search service tests
- `tests/unit/test_qna_service.py`: QnA service tests
- `tests/unit/test_eval_service.py`: Evaluation service tests
- `tests/unit/test_models.py`: Database model validation tests

### Contract Tests (API Endpoint Validation)

```bash
# Run contract tests
pytest tests/contract/ -v
```

**Example Contract Test**:
```python
# tests/contract/test_auth_api.py
import pytest
from httpx import AsyncClient
from app.main import app

@pytest.mark.asyncio
async def test_login_endpoint_contract():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/auth/login",
            json={
                "email": "test@example.com",
                "password": "password123"
            }
        )

        # Contract validation
        assert response.status_code in [200, 401]
        assert "detail" in response.json() or "user" in response.json()
```

### Integration Tests (Full User Journeys)

```bash
# Run integration tests (slower, requires API keys)
pytest tests/integration/ -v --run-integration
```

**Example Integration Test**:
```python
# tests/integration/test_document_upload_flow.py
@pytest.mark.integration
@pytest.mark.asyncio
async def test_complete_document_upload_and_qna_flow():
    # Setup: Create test user
    user = await create_test_user()

    # Upload document
    document = await upload_test_document(
        user, "./tests/fixtures/sample.pdf"
    )
    assert document.status == "uploading"

    # Wait for document to be ready
    await wait_for_document_status(document.id, "ready", timeout=180)

    # Ask question
    answer = await ask_question(
        document.id, "What is the main topic?"
    )
    assert len(answer) > 0

    # Verify QnA log was created
    logs = await get_qa_logs(document.id)
    assert len(logs) == 1

    # Cleanup
    await delete_test_document(document.id)
    await delete_test_user(user.id)
```

---

## Code Quality Checks

### Format Code with Black

```bash
# Format all Python files
black app/ tests/

# Check formatting without changing files
black --check app/ tests/
```

### Lint with Ruff

```bash
# Run linter
ruff check app/ tests/

# Auto-fix issues
ruff check --fix app/ tests/
```

### Type Checking with mypy

```bash
# Type check
mypy app/
```

### Pre-commit Hook (Optional)

```bash
# Create pre-commit hook
cat > .git/hooks/pre-commit << 'EOF'
#!/bin/bash
black --check app/ tests/ || exit 1
ruff check app/ tests/ || exit 1
pytest tests/unit/ -v || exit 1
EOF

chmod +x .git/hooks/pre-commit
```

---

## Common Development Tasks

### Add New API Endpoint

1. **Write contract test** (RED):
   ```python
   # tests/contract/test_new_endpoint.py
   async def test_new_endpoint_contract():
       # Define expected behavior
       pass
   ```

2. **Implement router** (GREEN):
   ```python
   # app/routers/new_feature.py
   from fastapi import APIRouter

   router = APIRouter()

   @router.get("/new-endpoint")
   async def new_endpoint():
       return {"message": "Hello"}
   ```

3. **Add to main app**:
   ```python
   # app/main.py
   from app.routers import new_feature

   app.include_router(new_feature.router, tags=["new-feature"])
   ```

### Add New Database Model

1. **Write model test** (RED):
   ```python
   # tests/unit/test_new_model.py
   def test_new_model_creation():
       # Define expected behavior
       pass
   ```

2. **Implement model** (GREEN):
   ```python
   # app/models/new_model.py
   from sqlalchemy import Column, Integer, String
   from app.db import Base

   class NewModel(Base):
       __tablename__ = "new_table"
       id = Column(Integer, primary_key=True)
       name = Column(String(255), nullable=False)
   ```

3. **Run migration**:
   ```python
   python -c "
   from app.db import Base, engine
   Base.metadata.create_all(bind=engine)
   "
   ```

### Debug LLM API Calls

```python
# Add detailed logging to service methods
import logging

logger = logging.getLogger(__name__)

async def call_gemini_api(prompt: str):
    logger.info(f"Calling Gemini API with prompt length: {len(prompt)}")

    try:
        response = await genai.generate_content(prompt)
        logger.info(f"Response received: {len(response.text)} chars")
        return response
    except Exception as e:
        logger.error(f"Gemini API error: {str(e)}", exc_info=True)
        raise
```

View logs:
```bash
# Run with debug logging
DEBUG=True uv run uvicorn app.main:app --reload --log-level debug
```

---

## Troubleshooting

### Issue: "Module 'app' not found"

**Solution**: Ensure you're in the project root and virtual environment is activated:
```bash
pwd  # Should show: /mnt/d/dev/elp_gemini
which python  # Should show: .venv/bin/python
```

### Issue: "Google API Key Invalid"

**Solution**:
1. Verify API key in .env file
2. Check key permissions at https://makersuite.google.com/
3. Ensure key has Gemini API access enabled

### Issue: "Database locked" errors

**Solution**: Enable WAL mode in SQLite:
```python
# In app/db.py
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()
```

### Issue: Tests failing with "asyncio" errors

**Solution**: Ensure pytest-asyncio is installed and configured:
```bash
uv pip install pytest-asyncio

# In pyproject.toml:
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

---

## Next Steps

1. **Implement User Authentication** (User Story 5, Priority P1)
   - Write failing tests for authentication
   - Implement authentication service
   - Create login/logout endpoints

2. **Implement Document Upload** (User Story 1, Priority P1)
   - Write failing tests for upload flow
   - Implement file upload handling
   - Integrate with Google File Search

3. **Implement QnA Feature** (User Story 1, Priority P1)
   - Write failing tests for QnA
   - Implement QnA service with RAG
   - Create QnA API endpoints

4. **Implement Evaluation** (User Story 2, Priority P2)
   - Write failing tests for evaluation
   - Implement evaluation service
   - Create evaluation API endpoints

5. **Implement Admin Dashboard** (User Story 4, Priority P4)
   - Write failing tests for admin features
   - Implement admin service
   - Create admin UI templates

---

## Resources

- **FastAPI Documentation**: https://fastapi.tiangolo.com/
- **Google Gemini API**: https://ai.google.dev/gemini-api/docs
- **SQLAlchemy**: https://docs.sqlalchemy.org/
- **Pytest**: https://docs.pytest.org/
- **Project Constitution**: `/mnt/d/dev/elp_gemini/.specify/memory/constitution.md`
- **API Contracts**: `/mnt/d/dev/elp_gemini/specs/001-ai-rag-eval-platform/contracts/openapi.yaml`
- **Data Model**: `/mnt/d/dev/elp_gemini/specs/001-ai-rag-eval-platform/data-model.md`

---

## Summary

✅ **Environment setup** with uv and dependencies
✅ **TDD workflow** with Red-Green-Refactor cycle
✅ **Testing strategy** for unit, contract, and integration tests
✅ **Code quality tools** configured (Black, Ruff, mypy)
✅ **Development server** ready to run
✅ **Troubleshooting guide** for common issues

**Ready to start implementation**: Follow the TDD cycle for each feature, starting with P1 user stories.
