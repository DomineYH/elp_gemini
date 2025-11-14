# Feature Specification: AI RAG-Based Document Evaluation & QnA Platform

**Feature Branch**: `001-ai-rag-eval-platform`
**Created**: 2025-11-13
**Status**: Draft
**Input**: User description: "AI 기반 문서 평가 및 QnA 플랫폼 - RAG 기반으로 사용자 문서를 업로드하고, 문서 내용에 대한 질의응답을 수행하며, 평가 기준에 따라 자동 평가 보고서를 생성하는 교육/평가 특화 어플리케이션"

## User Scenarios & Testing

### User Story 1 - Document Upload and Basic QnA (Priority: P1)

A student uploads their research paper and asks questions about its content to understand strengths and areas for improvement.

**Why this priority**: This is the core value proposition - enabling users to interact with their documents using AI. Without this, no other features provide value.

**Independent Test**: Can be fully tested by uploading a PDF, asking questions about specific sections, and receiving accurate context-aware responses. Delivers immediate value as a document QnA tool.

**Acceptance Scenarios**:

1. **Given** user is logged in, **When** they upload a PDF file and enter a title, **Then** the document appears in their document list with status "Ready"
2. **Given** user has uploaded a document, **When** they select it and ask "What is the main conclusion in Chapter 3?", **Then** system returns relevant excerpts from the document with an AI-generated answer
3. **Given** user is viewing QnA session, **When** they ask follow-up questions, **Then** system maintains conversation context and references previous questions
4. **Given** user's document contains sensitive information, **When** another user tries to access it, **Then** system blocks access and only shows documents owned by the requesting user

---

### User Story 2 - Automated Document Evaluation (Priority: P2)

A teacher uploads student assignment submissions and requests evaluation reports based on a predefined rubric to provide consistent feedback.

**Why this priority**: This differentiates the platform from simple QnA tools by providing structured evaluation capabilities, but requires the base document upload/QnA infrastructure.

**Independent Test**: Can be tested by uploading a document, selecting an evaluation template, and receiving a structured report with scores, criteria-based feedback, and improvement suggestions.

**Acceptance Scenarios**:

1. **Given** user has uploaded a document and a rubric exists, **When** they click "Generate Evaluation Report", **Then** system produces a report with scores, criteria-based feedback, and overall assessment
2. **Given** evaluation is complete, **When** user views the report, **Then** they see section-by-section feedback, numerical scores (if applicable), and specific improvement recommendations
3. **Given** user views past evaluations, **When** they access evaluation history, **Then** system displays all previous evaluation reports with timestamps and can be re-opened
4. **Given** evaluation criteria have changed, **When** user generates a new report, **Then** system uses the current active rubric version

---

### User Story 3 - Document Management (Priority: P3)

A user manages multiple documents by viewing their list, organizing them, and deleting documents they no longer need.

**Why this priority**: Essential for users with multiple documents, but the platform can function with a single document per user initially.

**Independent Test**: Can be tested by uploading multiple documents, viewing the complete list with metadata, and successfully deleting documents.

**Acceptance Scenarios**:

1. **Given** user has uploaded multiple documents, **When** they view their document list, **Then** they see all documents with title, upload date, and status
2. **Given** user selects a document, **When** they click delete, **Then** system prompts for confirmation and removes the document from their list
3. **Given** user has deleted a document, **When** they try to access it via old links, **Then** system returns "Document not found" error
4. **Given** document is being processed, **When** user views document list, **Then** status shows "Processing" and QnA/evaluation features are disabled until ready

---

### User Story 4 - Admin Dashboard and Monitoring (Priority: P4)

An administrator monitors platform usage, reviews user activity, views QnA logs, and manages system prompts to ensure service quality.

**Why this priority**: Critical for platform operators but not needed for end-user value delivery. Can be added after core user features are stable.

**Independent Test**: Can be tested by logging in as admin, viewing summary metrics (user count, document uploads, QnA requests), drilling into specific user activities, and updating system prompts.

**Acceptance Scenarios**:

1. **Given** admin is logged in, **When** they access dashboard, **Then** they see summary cards showing total users, documents uploaded (last 7 days), QnA requests, and evaluation runs
2. **Given** admin views user list, **When** they select a specific user, **Then** system displays that user's documents, evaluation reports, and QnA conversation logs
3. **Given** admin views QnA logs, **When** they filter by date range and user, **Then** system shows matching question-answer pairs with timestamps and prompt versions used
4. **Given** admin wants to improve AI responses, **When** they update a system prompt and activate it, **Then** all subsequent QnA/evaluation requests use the new prompt version
5. **Given** admin views evaluation reports, **When** they search by user or document, **Then** system displays matching reports with scores and feedback details

---

### User Story 5 - User Authentication and Isolation (Priority: P1)

Users securely log in and access only their own documents, ensuring data privacy and preventing unauthorized access.

**Why this priority**: Fundamental security requirement that must be in place from day one. Without this, data isolation is compromised.

**Independent Test**: Can be tested by creating multiple user accounts, verifying each user only sees their own documents, and attempting unauthorized access fails.

**Acceptance Scenarios**:

1. **Given** new user, **When** they sign up with email and password, **Then** account is created and they can log in
2. **Given** user is logged out, **When** they attempt to access documents, **Then** system redirects to login page
3. **Given** user logs in, **When** they view document list, **Then** only their own uploaded documents are visible
4. **Given** user tries to access another user's document URL directly, **When** request is processed, **Then** system returns "Access Denied" error

---

### Edge Cases

- What happens when user uploads extremely large files (>100MB)?
- How does system handle corrupted or password-protected PDF files?
- What happens when AI service is temporarily unavailable during QnA?
- How does system behave when evaluation rubric document is missing or inaccessible?
- What happens when user asks questions in multiple languages?
- How does system handle concurrent QnA sessions on the same document?
- What happens when user deletes a document while evaluation is in progress?
- How does admin rollback affect in-progress QnA sessions using old prompt?
- What happens when document contains images, tables, or complex formatting?
- How does system handle session timeout during long QnA conversations?

## Requirements

### Functional Requirements

- **FR-001**: System MUST allow registered users to upload PDF documents with title and metadata
- **FR-002**: System MUST index uploaded documents using RAG (File Search Tool) for semantic search
- **FR-003**: System MUST support document-based question answering that retrieves relevant content and generates responses
- **FR-004**: System MUST maintain conversation context within a QnA session for follow-up questions
- **FR-005**: System MUST isolate user data by user_id and random_key to prevent cross-user data access
- **FR-006**: System MUST generate evaluation reports based on predefined rubric documents and system prompts
- **FR-007**: System MUST store evaluation reports with scores, criteria-based feedback, and improvement recommendations
- **FR-008**: System MUST display user-specific document lists with title, upload date, and status
- **FR-009**: System MUST allow users to delete documents (logical or physical deletion based on policy)
- **FR-010**: System MUST authenticate users and establish secure sessions
- **FR-011**: System MUST provide admin dashboard showing aggregate metrics (user count, document count, QnA requests, evaluation runs)
- **FR-012**: System MUST allow admins to view individual user details including documents, evaluations, and QnA logs
- **FR-013**: System MUST allow admins to manage system prompts with versioning (QnA prompts and evaluation prompts)
- **FR-014**: System MUST track which prompt version was used for each QnA interaction and evaluation
- **FR-015**: System MUST log all QnA interactions with question, answer, model used, and timestamp
- **FR-016**: System MUST support filtering and searching of QnA logs by user, document, date range, and prompt version
- **FR-017**: System MUST validate uploaded files for supported formats (PDF) and reject files exceeding 50MB
- **FR-018**: System MUST handle document processing failures gracefully and update document status accordingly
- **FR-019**: System MUST support admin role with distinct permissions from regular users
- **FR-020**: System MUST persist all data (documents, QnA logs, evaluations, prompts) in local database with cloud storage only for RAG indexing

### Key Entities

- **User**: Represents platform users (students, teachers, researchers, professionals). Attributes include user ID, email, role (user/admin), registration date. Relationships: owns multiple documents, creates QnA sessions, generates evaluation reports.

- **Document**: Represents uploaded files for analysis. Attributes include document ID, user ID, random key (for isolation), title, upload timestamp, file path, processing status, cloud vector store reference. Relationships: belongs to one user, has multiple QnA sessions, has multiple evaluation reports.

- **QnA Session**: Represents question-answer interactions on a document. Attributes include session ID, document ID, user ID, conversation history (questions and answers), timestamps, model name, system prompt version. Relationships: belongs to one document and user.

- **Evaluation Report**: Represents automated assessment results. Attributes include report ID, document ID, user ID, evaluation template/rubric reference, scores, criteria feedback, overall assessment, generation timestamp, prompt version. Relationships: belongs to one document and user.

- **System Prompt**: Represents AI prompt templates for QnA and evaluation. Attributes include prompt ID, type (QnA/evaluation), content, version number, is_active flag, created timestamp. Relationships: used by QnA sessions and evaluation reports.

- **Rubric/Evaluation Template**: Represents evaluation criteria documents. Attributes include template ID, name, description, content/file reference, vector store reference, created date. Relationships: used by evaluation reports.

- **Admin User**: Specialized user type with elevated permissions. Attributes include all User attributes plus access to platform-wide data. Relationships: can view all users, documents, QnA logs, evaluation reports, and manage system prompts.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Users can upload a document and receive a successful QnA response within 3 minutes of upload completion
- **SC-002**: System maintains conversation context across at least 5 consecutive questions in a QnA session without losing relevance
- **SC-003**: Evaluation reports are generated within 2 minutes for documents up to 50 pages
- **SC-004**: 100% data isolation - users can only access their own documents with zero unauthorized access incidents
- **SC-005**: Admin dashboard loads summary metrics within 2 seconds
- **SC-006**: System prompt updates take effect on all new QnA/evaluation requests within 1 minute of activation
- **SC-007**: QnA responses reference accurate sections from the document with at least 85% relevance based on user queries
- **SC-008**: Evaluation reports include scores for all defined rubric criteria with specific feedback for each
- **SC-009**: Users can view their complete QnA history for any document
- **SC-010**: Admins can filter and search QnA logs by multiple criteria and retrieve results within 3 seconds

## Assumptions

- PDF is the primary document format (most common in education/research contexts)
- Google File Search Tool (or similar RAG service) is available for document indexing and retrieval
- Standard session-based authentication is sufficient for initial release (OAuth/SSO can be added later)
- Evaluation rubrics are provided as separate documents/templates rather than dynamically created by users
- Text-based QnA is the primary mode (no voice input/output initially)
- Single language support initially (Korean or English), with potential for multi-language expansion
- Document retention is indefinite unless explicitly deleted by user or admin
- System prompts are managed by administrators rather than individual users customizing their own prompts
- File size limit of 50MB is reasonable for most educational/research documents
- Local database storage is sufficient for metadata and logs; cloud storage used only for vector indexing
- Admin access is authenticated separately with distinct credentials from regular users
