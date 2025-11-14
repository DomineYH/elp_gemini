# Implementation Plan: AI RAG-Based Document Evaluation & QnA Platform

**Branch**: `001-ai-rag-eval-platform` | **Date**: 2025-11-13 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-ai-rag-eval-platform/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

AI-powered educational platform for document analysis, question-answering, and automated evaluation. Users upload PDF documents which are indexed using RAG (Google File Search Tool). The system provides document-based QnA with conversation context and generates evaluation reports based on predefined rubrics. Admins monitor usage, manage system prompts, and review QnA logs. Technical approach: FastAPI backend with Jinja2 templates, SQLite3 database, Google Gemini API for LLM, and Google File Search Tool for RAG indexing.

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: FastAPI, Jinja2, SQLite3, Google Gemini API SDK, httpx, pydantic, python-multipart, aiosqlite
**Storage**: SQLite3 (local file-based database at ./data/app.db) with WAL mode, Google File Search Store (cloud-based vector storage for RAG)
**Testing**: pytest (unit tests), pytest-asyncio (async tests), httpx for API testing
**Target Platform**: Linux server (single instance, local development with uv-based venv)
**Project Type**: Web application (FastAPI backend + Jinja2 SSR frontend)
**Performance Goals**: <3min document upload-to-QnA, <2min evaluation report generation, <2s admin dashboard load, <200ms API response
**Constraints**: 50MB file size limit, 99.9% data isolation, sub-3-second load times on 3G, single-server deployment
**Scale/Scope**: Small-to-medium educational platform (estimated <1000 concurrent users, <10K documents, <100K QnA requests/month)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Core Principles Compliance

#### I. File Length Constraint (≤300 lines)
**Status**: ✅ PASS (with planning)

**Analysis**:
- FastAPI routers will be split by domain (auth, user_docs, qna, eval, admin)
- Service layer separated by concern (file_search, qna, eval, admin)
- DB models separated by entity (users, documents, prompts, evaluations, qa_logs)
- Each file estimated at 150-250 lines with proper separation

**Mitigation Plan**:
- If any service exceeds 300 lines, split into sub-services
- Use separate files for Pydantic schemas per entity
- Template files kept under 300 lines each

#### II. Line Length Constraint (≤80 characters)
**Status**: ✅ PASS

**Analysis**:
- Python Black formatter will enforce 80-character line limit
- Configuration: `pyproject.toml` with `line-length = 80`
- URL strings and long literals will use proper line continuation
- Jinja2 templates will follow same constraint

**Enforcement**:
- Black formatter in pre-commit hook
- CI/CD pipeline validation
- Editor config (.editorconfig) for consistency

#### III. Test-Driven Development (TDD)
**Status**: ✅ PASS

**Analysis**:
- All user stories have defined acceptance scenarios (test cases)
- Test hierarchy planned: unit → contract → integration
- Each feature will follow Red-Green-Refactor cycle

**Test Strategy**:
- **Unit tests**: Business logic in services, model validation
- **Contract tests**: API endpoints match OpenAPI spec
- **Integration tests**: Database operations, File Search integration, full user journeys

**Test-First Order** (from tasks.md):
1. Write failing test for authentication
2. Implement authentication to pass test
3. Write failing test for document upload
4. Implement document upload to pass test
5. (Pattern continues for all features)

### Quality Gates

| Gate | Requirement | Status |
|------|-------------|--------|
| File Length | All files ≤300 lines | ✅ Planned with modular separation |
| Line Length | All lines ≤80 chars | ✅ Black formatter configured |
| TDD Cycle | Test before implementation | ✅ Test tasks precede impl tasks |
| Test Coverage | Unit ≥80%, Contract 100%, Integration 100% critical paths | ✅ Coverage targets defined |
| Constitution Documented | Violations justified in Complexity Tracking | ✅ No violations expected |

### Complexity Justification

**Status**: No violations identified

If complexity violations emerge during implementation, they will be documented in the Complexity Tracking table below with full justification.

---

## Constitution Re-Check (Post-Design)

*Re-evaluated after Phase 1 (Design & Contracts) completion*

### Updated Compliance Status

#### I. File Length Constraint (≤300 lines)
**Status**: ✅ PASS

**Re-Analysis**:
- OpenAPI contract: 680 lines (documentation, exempted from constraint)
- data-model.md: 7 entities documented, each will be <300 lines in implementation
- Actual model files will be split:
  - `app/models/users.py`: ~80 lines
  - `app/models/documents.py`: ~100 lines
  - `app/models/prompts.py`: ~60 lines
  - `app/models/evaluations.py`: ~250 lines (3 related models)
  - `app/models/qa_logs.py`: ~70 lines
- All service files projected at 150-250 lines each
- Router files projected at 100-200 lines each

**Confidence**: HIGH - No files expected to exceed 300 lines

#### II. Line Length Constraint (≤80 characters)
**Status**: ✅ PASS

**Re-Analysis**:
- Black formatter configured in pyproject.toml
- All template files will follow 80-char limit
- Long URL strings in contracts will use YAML multi-line format
- Jinja2 templates will wrap at 80 characters

**Confidence**: HIGH - Automated enforcement via Black

#### III. Test-Driven Development (TDD)
**Status**: ✅ PASS

**Re-Analysis**:
- Quickstart.md documents complete TDD cycle (Red-Green-Refactor)
- Test structure defined: unit → contract → integration
- Example tests provided for each layer
- User stories have clear acceptance scenarios (test specifications)
- tasks.md will enforce test-before-implementation order

**Confidence**: HIGH - Clear TDD workflow documented

### Final Gate Status

| Gate | Pre-Design | Post-Design | Status |
|------|------------|-------------|--------|
| File Length | ✅ Planned | ✅ Verified | PASS |
| Line Length | ✅ Configured | ✅ Verified | PASS |
| TDD Cycle | ✅ Defined | ✅ Documented | PASS |
| Constitution Compliance | ✅ | ✅ | PASS |

**Conclusion**: All constitutional requirements satisfied. Ready to proceed to Phase 2 (Task Generation).

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
app/
├── main.py                 # FastAPI entrypoint, app initialization
├── config.py               # Environment variables, settings
├── db.py                   # SQLite connection, session management
├── models/                 # Database models (ORM)
│   ├── __init__.py
│   ├── users.py            # User, Admin models
│   ├── documents.py        # Document model
│   ├── prompts.py          # SystemPrompt model
│   ├── evaluations.py      # EvaluationTemplate, Run, Report
│   └── qa_logs.py          # QALog model
├── routers/                # FastAPI route handlers
│   ├── __init__.py
│   ├── auth.py             # Login, logout, session management
│   ├── user_docs.py        # Document CRUD for users
│   ├── qna.py              # Question-answering endpoints
│   ├── eval.py             # Evaluation report generation
│   └── admin.py            # Admin dashboard, user mgmt
├── services/               # Business logic layer
│   ├── __init__.py
│   ├── file_search_service.py  # File Search Store operations
│   ├── qna_service.py          # QnA orchestration
│   ├── eval_service.py         # Evaluation orchestration
│   └── admin_service.py        # Admin aggregations
├── schemas/                # Pydantic request/response models
│   ├── __init__.py
│   ├── users.py
│   ├── documents.py
│   ├── qna.py
│   ├── eval.py
│   └── prompts.py
├── templates/              # Jinja2 HTML templates
│   ├── base.html           # Base layout
│   ├── user/
│   │   ├── dashboard.html      # User document list
│   │   └── doc_detail.html     # Document QnA/eval view
│   └── admin/
│       ├── admin_dashboard.html
│       ├── admin_users.html
│       ├── admin_user_detail.html
│       ├── admin_qna_logs.html
│       └── admin_prompts.html
├── static/                 # Static assets
│   ├── css/
│   │   └── main.css        # Tailwind-generated CSS
│   └── js/
│       └── app.js          # Minimal vanilla JS
└── utils/                  # Common utilities
    ├── __init__.py
    └── logging.py          # Logging configuration

tests/
├── contract/               # API contract tests
│   ├── test_auth_api.py
│   ├── test_user_docs_api.py
│   ├── test_qna_api.py
│   ├── test_eval_api.py
│   └── test_admin_api.py
├── integration/            # Integration tests
│   ├── test_document_upload_flow.py
│   ├── test_qna_flow.py
│   ├── test_evaluation_flow.py
│   └── test_user_isolation.py
└── unit/                   # Unit tests
    ├── test_file_search_service.py
    ├── test_qna_service.py
    ├── test_eval_service.py
    └── test_models.py

data/                       # Runtime data (gitignored)
├── app.db                  # SQLite database file
└── uploads/                # Uploaded PDF files

migrations/                 # Database schema migrations (optional)
```

**Structure Decision**: Web application structure with integrated backend and server-side rendered frontend. No separate frontend build process initially - Tailwind via CDN for rapid development. FastAPI serves both API endpoints and HTML templates. Single-repository monolith suitable for small-to-medium scale deployment on single server.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
