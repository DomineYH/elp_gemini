# Data Model: AI RAG-Based Document Evaluation & QnA Platform

**Branch**: `001-ai-rag-eval-platform` | **Phase**: 1 (Design) | **Date**: 2025-11-13

## Overview

This document defines the database schema, entity relationships, and data validation rules for the platform. All entities follow the project constitution (≤300 lines per file).

---

## Database Schema

### Technology: SQLite3 with SQLAlchemy ORM

**Configuration**:
- Journal Mode: WAL (Write-Ahead Logging)
- Foreign Keys: Enabled
- Busy Timeout: 5000ms

---

## Entity Definitions

### 1. User

**Purpose**: Represents platform users (students, teachers, researchers)

**Table**: `users`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY, AUTOINCREMENT | Unique user identifier |
| username | VARCHAR(255) | UNIQUE, NOT NULL, INDEX | User-chosen ID for login |
| hashed_password | VARCHAR(255) | NOT NULL | bcrypt hashed password |
| is_admin | BOOLEAN | NOT NULL, DEFAULT FALSE | Admin role flag |
| created_at | DATETIME | NOT NULL, DEFAULT CURRENT_TIMESTAMP | Registration timestamp |
| updated_at | DATETIME | NOT NULL, DEFAULT CURRENT_TIMESTAMP | Last update timestamp |

**Indexes**:
- `idx_users_username` on `username` (for login queries)

**Relationships**:
- One-to-Many with `documents` (user owns multiple documents)
- One-to-Many with `qa_logs` (user creates multiple QnA sessions)
- One-to-Many with `evaluation_runs` (user generates multiple evaluations)

**Validation Rules**:
- Username: 3-30 characters, alphanumeric + underscore, unique
- Password: Min 8 characters, at least one uppercase, one lowercase, one digit
- Username uniqueness enforced at database level

**SQLAlchemy Model** (app/models/users.py):
```python
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from app.db import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    is_admin = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
```

---

### 2. Document

**Purpose**: Represents uploaded PDF files for analysis

**Table**: `documents`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY, AUTOINCREMENT | Unique document identifier |
| user_id | INTEGER | NOT NULL, FOREIGN KEY → users.id, INDEX | Owner user ID |
| random_key | VARCHAR(64) | NOT NULL, INDEX | Random isolation key for RAG |
| title | VARCHAR(255) | NOT NULL | User-provided document title |
| file_path | VARCHAR(500) | NOT NULL | Local file system path |
| file_size | INTEGER | NOT NULL | File size in bytes |
| status | VARCHAR(50) | NOT NULL, DEFAULT 'uploading' | Processing status |
| file_search_file_id | VARCHAR(255) | NULLABLE | Google File Search file ID |
| store_id | VARCHAR(255) | NULLABLE | File Search Store ID |
| uploaded_at | DATETIME | NOT NULL, DEFAULT CURRENT_TIMESTAMP | Upload timestamp |
| updated_at | DATETIME | NOT NULL, DEFAULT CURRENT_TIMESTAMP | Last update timestamp |

**Status Values**:
- `uploading`: File upload in progress
- `indexing`: File Search indexing in progress
- `ready`: Document ready for QnA/evaluation
- `failed`: Processing failed
- `deleted`: Logically deleted (soft delete)

**Indexes**:
- `idx_documents_user_id` on `user_id` (for user document list queries)
- `idx_documents_random_key` on `random_key` (for RAG filtering)
- `idx_documents_status` on `status` (for status filtering)

**Relationships**:
- Many-to-One with `users` (document belongs to one user)
- One-to-Many with `qa_logs` (document has multiple QnA sessions)
- One-to-Many with `evaluation_runs` (document has multiple evaluations)

**Validation Rules**:
- Title: Max 255 characters, not empty
- File size: Max 50MB (52,428,800 bytes)
- Random key: 64 characters, cryptographically random, unique per document
- Status: Must be one of valid status values

**SQLAlchemy Model** (app/models/documents.py):
```python
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db import Base

class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    random_key = Column(String(64), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=False)
    status = Column(String(50), nullable=False, default="uploading", index=True)
    file_search_file_id = Column(String(255), nullable=True)
    store_id = Column(String(255), nullable=True)
    uploaded_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", backref="documents")
    qa_logs = relationship("QALog", back_populates="document")
    evaluation_runs = relationship("EvaluationRun", back_populates="document")
```

---

### 3. SystemPrompt

**Purpose**: Versioned AI prompts for QnA and evaluation

**Table**: `system_prompts`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY, AUTOINCREMENT | Unique prompt identifier |
| type | VARCHAR(50) | NOT NULL, INDEX | Prompt type (qna/evaluation) |
| version | INTEGER | NOT NULL | Version number |
| content | TEXT | NOT NULL | Prompt text content |
| is_active | BOOLEAN | NOT NULL, DEFAULT FALSE | Active version flag |
| created_by | INTEGER | FOREIGN KEY → users.id, NULLABLE | Admin who created |
| created_at | DATETIME | NOT NULL, DEFAULT CURRENT_TIMESTAMP | Creation timestamp |

**Type Values**:
- `qna`: Prompt for question-answering
- `evaluation`: Prompt for evaluation report generation

**Indexes**:
- `idx_system_prompts_type_active` on `(type, is_active)` (for active prompt lookup)
- Unique constraint on `(type, version)` (version uniqueness per type)

**Relationships**:
- One-to-Many with `qa_logs` (prompt version used in QnA)
- One-to-Many with `evaluation_runs` (prompt version used in evaluation)
- Many-to-One with `users` (created_by relationship)

**Validation Rules**:
- Type: Must be 'qna' or 'evaluation'
- Content: Not empty, max 10,000 characters
- Only one active prompt per type at any time (enforced at application level)

**Versioning Strategy**:
- Version numbers increment automatically per type
- Activating new version deactivates previous active version
- Old versions preserved for audit trail

**SQLAlchemy Model** (app/models/prompts.py):
```python
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db import Base

class SystemPrompt(Base):
    __tablename__ = "system_prompts"
    __table_args__ = (
        UniqueConstraint('type', 'version', name='uq_type_version'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String(50), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, default=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    # Relationships
    creator = relationship("User", backref="created_prompts")
```

---

### 4. EvaluationTemplate

**Purpose**: Rubric documents for automated evaluation

**Table**: `evaluation_templates`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY, AUTOINCREMENT | Unique template identifier |
| name | VARCHAR(255) | NOT NULL, UNIQUE | Template name |
| description | TEXT | NULLABLE | Template description |
| file_path | VARCHAR(500) | NOT NULL | Local file path to rubric |
| file_search_file_id | VARCHAR(255) | NULLABLE | Google File Search file ID |
| store_id | VARCHAR(255) | NULLABLE | File Search Store ID (rubric-store) |
| is_active | BOOLEAN | NOT NULL, DEFAULT TRUE | Active template flag |
| created_at | DATETIME | NOT NULL, DEFAULT CURRENT_TIMESTAMP | Creation timestamp |
| updated_at | DATETIME | NOT NULL, DEFAULT CURRENT_TIMESTAMP | Last update timestamp |

**Indexes**:
- `idx_evaluation_templates_name` on `name` (for template lookup)
- `idx_evaluation_templates_active` on `is_active` (for active templates)

**Relationships**:
- One-to-Many with `evaluation_runs` (template used in multiple evaluations)

**Validation Rules**:
- Name: Max 255 characters, unique, not empty
- File path: Valid path, file must exist

**SQLAlchemy Model** (app/models/evaluations.py - part 1):
```python
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db import Base

class EvaluationTemplate(Base):
    __tablename__ = "evaluation_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    file_path = Column(String(500), nullable=False)
    file_search_file_id = Column(String(255), nullable=True)
    store_id = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    # Relationships
    evaluation_runs = relationship("EvaluationRun", back_populates="template")
```

---

### 5. EvaluationRun

**Purpose**: Tracks evaluation execution for a document

**Table**: `evaluation_runs`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY, AUTOINCREMENT | Unique run identifier |
| document_id | INTEGER | NOT NULL, FOREIGN KEY → documents.id, INDEX | Document being evaluated |
| user_id | INTEGER | NOT NULL, FOREIGN KEY → users.id, INDEX | User who requested |
| template_id | INTEGER | NOT NULL, FOREIGN KEY → evaluation_templates.id | Template used |
| prompt_id | INTEGER | NOT NULL, FOREIGN KEY → system_prompts.id | Prompt version used |
| status | VARCHAR(50) | NOT NULL, DEFAULT 'pending' | Execution status |
| model_name | VARCHAR(100) | NOT NULL | Gemini model used |
| started_at | DATETIME | NOT NULL, DEFAULT CURRENT_TIMESTAMP | Start timestamp |
| completed_at | DATETIME | NULLABLE | Completion timestamp |
| error_message | TEXT | NULLABLE | Error details if failed |

**Status Values**:
- `pending`: Evaluation queued
- `running`: Evaluation in progress
- `success`: Evaluation completed successfully
- `failed`: Evaluation failed

**Indexes**:
- `idx_evaluation_runs_document_id` on `document_id` (for document evaluations)
- `idx_evaluation_runs_user_id` on `user_id` (for user evaluations)
- `idx_evaluation_runs_status` on `status` (for status filtering)

**Relationships**:
- Many-to-One with `documents` (run evaluates one document)
- Many-to-One with `users` (run requested by one user)
- Many-to-One with `evaluation_templates` (run uses one template)
- Many-to-One with `system_prompts` (run uses one prompt version)
- One-to-One with `evaluation_reports` (run produces one report)

**Validation Rules**:
- Status: Must be one of valid status values
- Model name: Not empty, max 100 characters
- completed_at: Must be after started_at if present

**SQLAlchemy Model** (app/models/evaluations.py - part 2):
```python
class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    template_id = Column(Integer, ForeignKey("evaluation_templates.id"), nullable=False)
    prompt_id = Column(Integer, ForeignKey("system_prompts.id"), nullable=False)
    status = Column(String(50), nullable=False, default="pending", index=True)
    model_name = Column(String(100), nullable=False)
    started_at = Column(DateTime, nullable=False, server_default=func.now())
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    # Relationships
    document = relationship("Document", back_populates="evaluation_runs")
    user = relationship("User", backref="evaluation_runs")
    template = relationship("EvaluationTemplate", back_populates="evaluation_runs")
    prompt = relationship("SystemPrompt", backref="evaluation_runs")
    report = relationship("EvaluationReport", uselist=False, back_populates="run")
```

---

### 6. EvaluationReport

**Purpose**: Stores evaluation results with scores and feedback

**Table**: `evaluation_reports`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY, AUTOINCREMENT | Unique report identifier |
| run_id | INTEGER | NOT NULL, FOREIGN KEY → evaluation_runs.id, UNIQUE | Associated run |
| overall_score | FLOAT | NULLABLE | Overall numeric score |
| criteria_scores | JSON | NULLABLE | JSON object with per-criterion scores |
| feedback | TEXT | NOT NULL | Detailed feedback text |
| improvement_suggestions | TEXT | NULLABLE | Improvement recommendations |
| created_at | DATETIME | NOT NULL, DEFAULT CURRENT_TIMESTAMP | Report generation timestamp |

**JSON Schema for criteria_scores**:
```json
{
  "criterion_1": {"score": 8.5, "max_score": 10, "feedback": "..."},
  "criterion_2": {"score": 7.0, "max_score": 10, "feedback": "..."}
}
```

**Indexes**:
- `idx_evaluation_reports_run_id` on `run_id` (for run-to-report lookup)

**Relationships**:
- One-to-One with `evaluation_runs` (report belongs to one run)

**Validation Rules**:
- Feedback: Not empty, max 50,000 characters
- Overall score: Between 0 and 100 if present
- criteria_scores: Valid JSON structure if present

**SQLAlchemy Model** (app/models/evaluations.py - part 3):
```python
class EvaluationReport(Base):
    __tablename__ = "evaluation_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("evaluation_runs.id"), nullable=False, unique=True)
    overall_score = Column(Float, nullable=True)
    criteria_scores = Column(JSON, nullable=True)
    feedback = Column(Text, nullable=False)
    improvement_suggestions = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    # Relationships
    run = relationship("EvaluationRun", back_populates="report")
```

---

### 7. QALog

**Purpose**: Records question-answer interactions

**Table**: `qa_logs`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY, AUTOINCREMENT | Unique log identifier |
| document_id | INTEGER | NOT NULL, FOREIGN KEY → documents.id, INDEX | Document queried |
| user_id | INTEGER | NOT NULL, FOREIGN KEY → users.id, INDEX | User who asked |
| prompt_id | INTEGER | NOT NULL, FOREIGN KEY → system_prompts.id | Prompt version used |
| question | TEXT | NOT NULL | User's question |
| answer | TEXT | NOT NULL | AI-generated answer |
| model_name | VARCHAR(100) | NOT NULL | Gemini model used |
| latency_ms | INTEGER | NULLABLE | Response time in milliseconds |
| created_at | DATETIME | NOT NULL, DEFAULT CURRENT_TIMESTAMP | Interaction timestamp |

**Indexes**:
- `idx_qa_logs_document_id` on `document_id` (for document QnA history)
- `idx_qa_logs_user_id` on `user_id` (for user QnA history)
- `idx_qa_logs_created_at` on `created_at` (for time-based queries)

**Relationships**:
- Many-to-One with `documents` (log belongs to one document)
- Many-to-One with `users` (log belongs to one user)
- Many-to-One with `system_prompts` (log uses one prompt version)

**Validation Rules**:
- Question: Not empty, max 5,000 characters
- Answer: Not empty, max 50,000 characters
- Model name: Not empty, max 100 characters
- Latency: Positive integer if present

**SQLAlchemy Model** (app/models/qa_logs.py):
```python
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db import Base

class QALog(Base):
    __tablename__ = "qa_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    prompt_id = Column(Integer, ForeignKey("system_prompts.id"), nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    model_name = Column(String(100), nullable=False)
    latency_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now(), index=True)

    # Relationships
    document = relationship("Document", back_populates="qa_logs")
    user = relationship("User", backref="qa_logs")
    prompt = relationship("SystemPrompt", backref="qa_logs")
```

---

## Entity Relationship Diagram

```
┌─────────────────┐
│     User        │
├─────────────────┤
│ id (PK)         │
│ username        │◄─────────┐
│ hashed_password │          │
│ is_admin        │          │
└─────────────────┘          │
        │                    │
        │ 1:N                │ 1:N
        ▼                    │
┌─────────────────┐          │
│   Document      │          │
├─────────────────┤          │
│ id (PK)         │          │
│ user_id (FK)    │──────────┘
│ random_key      │
│ title           │
│ status          │
└─────────────────┘
        │
        │ 1:N
        ├──────────────────┐
        │                  │
        ▼                  ▼
┌─────────────────┐  ┌─────────────────┐
│     QALog       │  │ EvaluationRun   │
├─────────────────┤  ├─────────────────┤
│ id (PK)         │  │ id (PK)         │
│ document_id(FK) │  │ document_id(FK) │
│ user_id (FK)    │  │ user_id (FK)    │
│ prompt_id (FK)  │  │ template_id(FK) │
│ question        │  │ prompt_id (FK)  │
│ answer          │  │ status          │
└─────────────────┘  └─────────────────┘
        │                    │
        │ N:1                │ 1:1
        ▼                    ▼
┌─────────────────┐  ┌─────────────────┐
│ SystemPrompt    │  │EvaluationReport │
├─────────────────┤  ├─────────────────┤
│ id (PK)         │  │ id (PK)         │
│ type            │  │ run_id (FK)     │
│ version         │  │ overall_score   │
│ content         │  │ criteria_scores │
│ is_active       │  │ feedback        │
└─────────────────┘  └─────────────────┘
                            ▲
                            │ N:1
                            │
                    ┌───────────────────┐
                    │EvaluationTemplate │
                    ├───────────────────┤
                    │ id (PK)           │
                    │ name              │
                    │ file_path         │
                    │ is_active         │
                    └───────────────────┘
```

---

## State Transitions

### Document Status Flow
```
uploading → indexing → ready
    │           │         │
    └───────────┴─────────┴──→ failed
                                  │
                            (retry possible)

ready → deleted (soft delete, cleanup job can purge)
```

### Evaluation Run Status Flow
```
pending → running → success
    │        │
    └────────┴─────→ failed (with error_message)

(No retry mechanism in initial version)
```

---

## Data Isolation Strategy

**Principle**: Users can only access their own data

**Implementation**:
1. **Document Access**: All document queries filtered by `user_id`
2. **RAG Isolation**: File Search queries use metadata filter:
   ```
   user_id="{user.id}" AND random_key="{document.random_key}"
   ```
3. **QA Logs**: Filtered by `user_id` for user views
4. **Evaluation Runs/Reports**: Filtered by `user_id` for user views
5. **Admin Override**: Admins can view all data but with explicit admin check

**Database Constraints**:
- Foreign keys enforce referential integrity
- Application layer enforces user_id filtering on all queries
- No direct user-to-user relationships in schema

---

## Database Initialization

**Migration Strategy** (optional for initial version):
- Use Alembic for schema migrations if needed
- For MVP, `Base.metadata.create_all()` is sufficient

**Initial Data**:
- Create default admin user (via seed script)
- Create default system prompts for QnA and evaluation (version 1)
- Create default evaluation template (if applicable)

**Seed Script** (app/db.py):
```python
def init_db():
    Base.metadata.create_all(bind=engine)

    # Create default admin
    admin = User(
        username="admin",
        hashed_password=pwd_context.hash("admin1234"),
        is_admin=True
    )
    db.add(admin)

    # Create default QnA prompt
    qna_prompt = SystemPrompt(
        type="qna",
        version=1,
        content="You are a helpful assistant...",
        is_active=True,
        created_by=admin.id
    )
    db.add(qna_prompt)

    db.commit()
```

---

## Summary

✅ **7 entities defined** with complete schemas
✅ **All relationships documented** with cardinality
✅ **Validation rules specified** for data integrity
✅ **Indexes planned** for query performance
✅ **State transitions documented** for workflows
✅ **Data isolation strategy** ensures user privacy
✅ **SQLAlchemy models ready** for implementation

**File Size Compliance**: Each model file will be <300 lines when implemented per constitution requirements.

**Next Step**: Generate API contracts based on these entities.
