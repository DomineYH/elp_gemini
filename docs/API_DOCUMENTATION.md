# API 문서

## 문서 정보
- **작성일**: 2025-11-22
- **버전**: 2.0
- **기반**: 리팩토링 후 새로운 API
- **Base URL**: `http://localhost:8000`

---

## 인증

모든 API는 JWT 토큰 기반 인증을 사용합니다.

### 헤더
```
Authorization: Bearer {access_token}
```

### 사용자 등급
- **일반 사용자**: 지도안, QnA, 평가 접근 가능
- **관리자**: 모든 기능 + 평가기준 관리

---

## 1. 지도안 관리 API

### 1.1 지도안 업로드

**Endpoint**: `POST /api/lessonplans/upload`

**설명**: 사용자의 지도안 파일을 업로드합니다.

**인증**: 필수

**Request**:
```
Content-Type: multipart/form-data

{
  "file": (binary)
}
```

**Response** (201 Created):
```json
{
  "username": "test_user",
  "filename": "test_user_lessonplan.pdf",
  "file_size": 102400,
  "file_path": "data/lessonplan/test_user_lessonplan.pdf",
  "created_at": "2025-11-22T10:00:00"
}
```

**Error Responses**:
- `400`: 파일 검증 실패
- `500`: 업로드 오류

---

### 1.2 지도안 목록 조회

**Endpoint**: `GET /api/lessonplans`

**설명**: 사용자의 지도안 목록을 조회합니다.

**인증**: 필수

**Response** (200 OK):
```json
{
  "username": "test_user",
  "lessonplans": [
    {
      "filename": "test_user_lessonplan1.pdf",
      "file_size": 102400,
      "created_at": "2025-11-22T10:00:00"
    }
  ],
  "total_count": 1
}
```

---

### 1.3 지도안 다운로드

**Endpoint**: `GET /api/lessonplans/{filename}/download`

**설명**: 지도안 파일을 다운로드합니다.

**인증**: 필수

**Path Parameters**:
- `filename`: 파일명

**Response** (200 OK):
```
Content-Type: application/octet-stream
Content-Disposition: attachment; filename="{filename}"

(binary file data)
```

**Error Responses**:
- `404`: 파일을 찾을 수 없음
- `500`: 다운로드 오류

---

### 1.4 지도안 삭제

**Endpoint**: `DELETE /api/lessonplans/{filename}`

**설명**: 지도안 파일을 삭제합니다.

**인증**: 필수

**Path Parameters**:
- `filename`: 파일명

**Response** (204 No Content):
```
(empty body)
```

**Error Responses**:
- `404`: 파일을 찾을 수 없음
- `500`: 삭제 오류

---

## 2. QnA API

### 2.1 QnA 세션 생성

**Endpoint**: `POST /api/qna/sessions`

**설명**: 지도안 기반 QnA 세션을 생성합니다.

**인증**: 필수

**Request**:
```json
{
  "lessonplan_filename": "test_user_lessonplan.pdf"
}
```

**Response** (201 Created):
```json
{
  "session_id": 1,
  "user_id": 1,
  "lessonplan_filename": "test_user_lessonplan.pdf",
  "created_at": "2025-11-22T10:00:00"
}
```

**Error Responses**:
- `500`: 세션 생성 실패

---

### 2.2 질문하기

**Endpoint**: `POST /api/qna/sessions/{session_id}/ask`

**설명**: 세션에서 질문을 하고 답변을 받습니다.

**인증**: 필수

**Path Parameters**:
- `session_id`: 세션 ID

**Request**:
```json
{
  "question": "이 지도안의 학습 목표는 무엇인가요?"
}
```

**Response** (200 OK):
```json
{
  "session_id": 1,
  "question": "이 지도안의 학습 목표는 무엇인가요?",
  "answer": "이 지도안의 학습 목표는...",
  "latency_ms": 1500,
  "citations": [
    {
      "page": 1,
      "text": "학습 목표: ..."
    }
  ]
}
```

**Error Responses**:
- `404`: 세션을 찾을 수 없음
- `500`: 질문 처리 실패

---

### 2.3 대화 히스토리 조회

**Endpoint**: `GET /api/qna/sessions/{session_id}/history`

**설명**: 세션의 대화 히스토리를 조회합니다.

**인증**: 필수

**Path Parameters**:
- `session_id`: 세션 ID

**Response** (200 OK):
```json
{
  "session_id": 1,
  "messages": [
    {
      "id": 1,
      "session_id": 1,
      "role": "user",
      "content": "이 지도안의 학습 목표는 무엇인가요?",
      "created_at": "2025-11-22T10:00:00"
    },
    {
      "id": 2,
      "session_id": 1,
      "role": "assistant",
      "content": "이 지도안의 학습 목표는...",
      "created_at": "2025-11-22T10:00:05"
    }
  ],
  "total_count": 2
}
```

**Error Responses**:
- `500`: 히스토리 조회 실패

---

## 3. 평가 API

### 3.1 평가 실행

**Endpoint**: `POST /api/evaluations`

**설명**: 지도안 평가를 실행하고 결과를 저장합니다.

**인증**: 필수

**Request**:
```json
{
  "lessonplan_filename": "test_user_lessonplan.pdf",
  "evaluation_type": "comprehensive"
}
```

**Response** (201 Created):
```json
{
  "username": "test_user",
  "lessonplan_filename": "test_user_lessonplan.pdf",
  "analysis_filename": "test_user_test_user_lessonplan.pdf.md",
  "evaluation_type": "comprehensive",
  "result_summary": "종합 평가 결과...",
  "latency_ms": 3000
}
```

**Error Responses**:
- `400`: 잘못된 요청 (파일 없음 등)
- `500`: 평가 실행 실패

---

### 3.2 평가 결과 조회

**Endpoint**: `GET /api/evaluations/{filename}`

**설명**: 저장된 평가 결과를 조회합니다.

**인증**: 필수

**Path Parameters**:
- `filename`: 분석 결과 파일명

**Response** (200 OK):
```json
{
  "filename": "test_user_test_user_lessonplan.pdf.md",
  "content": "# 평가 결과\n\n...",
  "file_size": 2048
}
```

**Error Responses**:
- `404`: 평가 결과를 찾을 수 없음
- `500`: 결과 조회 실패

---

## 4. 관리자 - 평가기준 API

### 4.1 평가기준 업로드

**Endpoint**: `POST /api/admin/criteria/upload`

**설명**: 평가기준 파일을 Vector DB에 업로드합니다.

**인증**: 필수 (관리자 전용)

**Request**:
```
Content-Type: multipart/form-data

{
  "file": (binary)
}
```

**Response** (201 Created):
```json
{
  "file_id": "files/xyz123",
  "display_name": "evaluation_criteria.pdf",
  "file_size": 204800,
  "upload_status": "completed"
}
```

**Error Responses**:
- `400`: 파일 검증 실패
- `403`: 권한 없음 (관리자 아님)
- `500`: 업로드 오류

---

### 4.2 평가기준 삭제

**Endpoint**: `DELETE /api/admin/criteria`

**설명**: 모든 평가기준을 삭제합니다.

**인증**: 필수 (관리자 전용)

**Note**: Gemini File Search API 제약으로 개별 문서 삭제
불가 → Store 재생성으로 전체 삭제

**Response** (200 OK):
```json
{
  "success": true,
  "message": "모든 평가기준이 삭제되었습니다.",
  "deleted_count": 0
}
```

**Error Responses**:
- `403`: 권한 없음 (관리자 아님)
- `500`: 삭제 오류

---

## 에러 코드 요약

| 코드 | 의미 | 설명 |
|------|------|------|
| 200 | OK | 성공 |
| 201 | Created | 생성 성공 |
| 204 | No Content | 삭제 성공 |
| 400 | Bad Request | 잘못된 요청 |
| 401 | Unauthorized | 인증 실패 |
| 403 | Forbidden | 권한 없음 |
| 404 | Not Found | 리소스 없음 |
| 500 | Internal Server Error | 서버 오류 |

---

## 사용 예시

### Python (httpx)

```python
import httpx

# 로그인
response = httpx.post(
    "http://localhost:8000/api/auth/login",
    json={
        "username": "test_user",
        "password": "test_password"
    }
)
token = response.json()["access_token"]

# 지도안 업로드
with open("lessonplan.pdf", "rb") as f:
    response = httpx.post(
        "http://localhost:8000/api/lessonplans/upload",
        files={"file": f},
        headers={"Authorization": f"Bearer {token}"}
    )
    print(response.json())
```

---

**작성자**: Claude Code (기계사제)
**최종 수정**: 2025-11-22
**버전**: 2.0
