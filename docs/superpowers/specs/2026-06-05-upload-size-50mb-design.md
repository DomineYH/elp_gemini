# 파일 업로드 한도 50MB 단일화 (config 단일 출처)

- 날짜: 2026-06-05
- 브랜치: `feat/upload-size-50mb`
- 상태: 설계 승인됨

## 배경 / 문제

파일 업로드 최대 크기가 코드베이스 전반에서 **50MB로 의도**되어 있으나(`.env`, `app/config.py`, `README.md`, `.env.example`, `update_env.py` 모두 `MAX_UPLOAD_SIZE=52428800`), 실제 검증을 담당하는 `FileValidator.MAX_FILE_SIZE`만 **10MB로 하드코딩**되어 그 설정값을 무시한다.

결과적으로:
- 대시보드 업로드(`app/routers/views.py` → `DASHBOARD_MAX_UPLOAD_SIZE = FileValidator.MAX_FILE_SIZE`)
- 평가기준 업로드(`app/routers/admin/criteria.py` → `FileValidator()`)
- 프론트엔드(`app/static/js/criteria_upload.js`, `app/templates/admin/criteria_upload.html`)

모두 10MB로 동작한다. 설정(50MB)과 enforcement(10MB)가 서로 다른 출처로 갈라져 있는 것이 근본 원인이다.

## 목표

1. 파일 업로드 한도를 **50MB로 통일**한다.
2. 한도를 **단일 출처(`settings.MAX_UPLOAD_SIZE`)에서 파생**시켜 불일치 재발을 방지한다.
3. 프론트엔드 표기/검증도 백엔드 값에서 자동 동기화되게 한다.

## 비목표 (Out of scope)

- Google File Search 자체 한도(문서당 100MB)와의 관계 변경 없음. 50MB는 그 이하로 안전.
- `.env`/`config.py`/`README.md` 등 이미 50MB인 설정값 변경 없음(단일 출처로 그대로 사용).
- 업로드 파이프라인의 다른 검증(PDF 시그니처, 악성 패턴 등) 변경 없음.

## 단일 출처

`settings.MAX_UPLOAD_SIZE` ( `.env` 의 `MAX_UPLOAD_SIZE=52428800` = 50MB ). 향후 한도 조정은 이 한 곳만 수정하면 백엔드/프론트 전체에 반영된다.

## 변경 사항

### 1. `app/services/file_validator.py`
- `from app.config import settings` 추가.
- 하드코딩 상수 `MAX_FILE_SIZE = 10 * 1024 * 1024` 제거.
- `__init__(self, max_size_mb=None)`에서 `max_size_mb` 미지정 시 `settings.MAX_UPLOAD_SIZE`(바이트)를 사용.
- 관련 주석("최대 파일 크기 (10MB)") 갱신.

### 2. `app/routers/views.py`
- `from app.config import settings` 추가.
- `DASHBOARD_MAX_UPLOAD_SIZE = settings.MAX_UPLOAD_SIZE` 로 변경(`FileValidator.MAX_FILE_SIZE` 의존 제거).
- 모듈 레벨 변수 유지 → 기존 테스트의 monkeypatch(`DASHBOARD_MAX_UPLOAD_SIZE = 8`) 호환.

### 3. `app/routers/admin/criteria_views.py`
- `from app.config import settings` 추가.
- `criteria_upload_page` 의 `TemplateResponse` 컨텍스트에 `"max_upload_size": settings.MAX_UPLOAD_SIZE` 추가.

### 4. `app/templates/admin/criteria_upload.html`
- `PDF 파일 (최대 10MB)` → `PDF 파일 (최대 {{ (max_upload_size / 1024 / 1024) | round | int }}MB)`.
- `criteria_upload.js` 로드 직전에 주입: `<script>window.MAX_UPLOAD_SIZE = {{ max_upload_size }};</script>`.

### 5. `app/static/js/criteria_upload.js`
- `const maxSize = window.MAX_UPLOAD_SIZE || 50 * 1024 * 1024;` (주입값 우선, fallback 50MB).
- 에러 메시지·주석을 동적화: `${(maxSize / 1024 / 1024).toFixed(0)}MB`.

## 테스트 (TDD)

먼저 실패하는 테스트를 작성하고(현재 10MB라 실패) → 구현 후 통과시킨다.

- 신규 회귀 테스트:
  - `FileValidator().max_file_size == settings.MAX_UPLOAD_SIZE` ( == 52428800 ).
  - `app.routers.views.DASHBOARD_MAX_UPLOAD_SIZE == settings.MAX_UPLOAD_SIZE`.
- 기존 대시보드 업로드 테스트(`tests/test_dashboard_upload_creates_upload_row.py`, 8바이트 monkeypatch)는 영향 없음 → 통과 유지 확인.
- 전체 스위트는 변경 전후 baseline 대비 신규 실패 0건이어야 한다(레포의 pre-existing 실패는 무관).

## 검증 기준 (Success criteria)

1. 신규 회귀 테스트 통과.
2. `git grep`으로 `10 * 1024 * 1024` / `최대 10MB` / `10MB를 초과` 잔존 0건(업로드 경로 한정).
3. 전체 pytest: 변경으로 인한 신규 실패 0건(baseline diff).
4. 업로드 한도가 `settings.MAX_UPLOAD_SIZE` 단일 출처에서 파생됨.

## 작업 흐름

스펙 커밋 → GitHub 이슈 등록 → 구현 계획(writing-plans) → TDD 구현 → 전체 테스트 검증 → PR 등록(이슈 링크).
