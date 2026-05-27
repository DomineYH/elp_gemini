# 분석 보고서 - 참고 문서 결정론적 표시 및 모델명 노출 제거 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 분석 보고서의 `### File Search 참고 문서` 섹션을 활성 평가기준 표시 이름(alias) + 분석 대상 수업지도안 원본 파일명으로 결정론적으로 렌더링하고, 보고서에서 모델명(`**분석 모델**: ...`)이 노출되지 않도록 한다.

**Architecture:** Gemini가 생성한 raw 보고서를 `_post_process_report`에서 서버 측 데이터로 치환한다. 활성 평가기준 alias는 이미 분석 흐름에서 호출되는 `CriteriaAliasMapService.fetch()`를 재활용하여 가져온다. 신규 분석부터 적용하며 디스크의 과거 보고서는 변경하지 않는다.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy(async), Gemini File Search, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-05-27-analysis-report-citation-and-model-name-design.md`

**Related issue:** https://github.com/DomineYH/elp_gemini/issues/82

---

## File Structure

**Files modified:**
- `prompt/prompt.md` — `lesson_analysis` 섹션에서 `**분석 모델**: {model_name}` 줄 1개 삭제
- `app/services/lessonplan_analysis_service.py`
  - `_build_analysis_prompt`: `{model_name}` 치환 코드 제거
  - `_post_process_report`: 시그니처에 옵션 인자 추가 + 모델명 줄 제거 단계 + File Search 섹션 치환 단계
  - 신규 헬퍼: `_collect_active_criteria_display_names`, `_render_file_search_references_section`, `_resolve_lessonplan_original_filename`
  - `analyze_lesson_plan`: alias 수집 + 원본 파일명 결정 + 후처리 호출 인자 전달

**Files created:**
- 없음 (기존 단위 테스트 파일을 확장)

**Tests modified:**
- `tests/unit/test_lessonplan_analysis_service.py` — 새 케이스 추가
- `tests/test_lessonplan_analysis_service.py` — 기존 케이스 회귀 방지 확인 (변경 불필요)

---

## Pre-flight: 기준 테스트 통과 확인

- [ ] **Step 0-1: 기준 테스트 실행으로 회귀 방지 베이스라인 확보**

Run:
```bash
pytest tests/unit/test_lessonplan_analysis_service.py -v
```

Expected: 모든 기존 테스트 PASS. 이후 각 Task에서 회귀 없는지 동일 명령으로 확인.

만약 기준 상태에서 실패가 있다면 멈추고 보고. 이후 변경이 회귀를 일으킨 건지 분리하기 어려워진다.

---

## Task 1: 프롬프트 템플릿에서 모델명 줄 제거

**Files:**
- Modify: `prompt/prompt.md` (lesson_analysis 섹션 헤더 블록)

**Goal:** 보고서 템플릿의 헤더 블록에서 `**분석 모델**: {model_name}` 줄을 제거. 이로써 LLM이 새 분석에서 이 줄을 더 이상 생성하지 않는다.

- [ ] **Step 1-1: 현재 헤더 블록 확인**

Read `prompt/prompt.md` 의 `## lesson_analysis` 섹션 하위 코드블록의 헤더 부분. 현재 다음과 같다:

```markdown
> **분석 개요**
> - **분석 일시**: [YYYY-MM-DD HH:MM]
> - **분석 모델**: {model_name}
```

- [ ] **Step 1-2: 모델명 줄 삭제**

`> - **분석 모델**: {model_name}` 줄 하나만 삭제한다. `> **분석 개요**`와 `> - **분석 일시**: [YYYY-MM-DD HH:MM]` 줄은 보존한다.

수정 후:

```markdown
> **분석 개요**
> - **분석 일시**: [YYYY-MM-DD HH:MM]
```

- [ ] **Step 1-3: prompt.md 다른 곳에 `{model_name}` 잔여 없는지 확인**

Run:
```bash
grep -n "{model_name}" prompt/prompt.md
```

Expected: 출력 없음 (exit code 1). 만약 다른 위치에 있다면 본 작업 범위 밖이므로 그대로 두되 보고.

- [ ] **Step 1-4: 커밋**

```bash
git add prompt/prompt.md
git commit -m "feat(prompt): remove model name line from lesson_analysis header

분석 보고서 헤더에서 내부 모델 식별자 노출 줄 삭제. 분석 일시는 유지.

Refs: #82"
```

---

## Task 2: `_build_analysis_prompt`에서 `{model_name}` 치환 코드 제거

**Files:**
- Modify: `app/services/lessonplan_analysis_service.py:574-577`
- Test: `tests/unit/test_lessonplan_analysis_service.py` (신규 케이스 추가)

**Goal:** `_build_analysis_prompt` 내부에서 `system_prompt.replace("{model_name}", self.model_name)`을 호출하던 줄을 제거한다. `self.model_name`은 `generate_content` 호출에서 여전히 사용되므로 필드 자체는 유지.

- [ ] **Step 2-1: 회귀 방지용 실패 테스트 작성**

`tests/unit/test_lessonplan_analysis_service.py`의 `TestLessonPlanAnalysisService` 클래스에 추가:

```python
    def test_build_analysis_prompt_omits_model_name(self, service):
        """프롬프트에서 모델 이름이 더 이상 치환/포함되지 않는다."""
        # Given: 템플릿에 {model_name} 플레이스홀더가 그대로 남아 있는 경우에도
        #         치환되지 않고, 동시에 빌더가 self.model_name 을 본문에 끼워넣지도
        #         않아야 한다.
        system_prompt = (
            "수업 지도안 평가 시스템 프롬프트\n"
            "분석 모델: {model_name}"
        )

        # When
        result = service._build_analysis_prompt(
            system_prompt,
            rubric_store_id="rubric-store",
            lesson_store_id="lesson-store",
        )

        # Then: 실제 모델 식별자(self.model_name)는 본문에 등장하지 않는다
        assert service.model_name not in result
        # 그리고 {model_name} 플레이스홀더도 치환되지 않은 채 그대로다
        #  (이 줄은 prompt.md 에서 삭제되었지만, 빌더 단위로는 input string 의
        #   해당 토큰을 더 이상 치환하지 않음을 보장하기 위한 검사)
        assert "{model_name}" in result
```

- [ ] **Step 2-2: 테스트 실행으로 실패 확인**

Run:
```bash
pytest tests/unit/test_lessonplan_analysis_service.py::TestLessonPlanAnalysisService::test_build_analysis_prompt_omits_model_name -v
```

Expected: FAIL — 현재 `_build_analysis_prompt`는 `{model_name}`을 `self.model_name`으로 치환하므로 첫 번째 assertion에서 실패한다.

- [ ] **Step 2-3: 치환 코드 제거**

`app/services/lessonplan_analysis_service.py`의 `_build_analysis_prompt` 메서드에서 다음 4줄을 삭제:

```python
        # 모델 이름 플레이스홀더 치환
        system_prompt = system_prompt.replace(
            "{model_name}", self.model_name
        )
```

- [ ] **Step 2-4: 새 테스트 + 기존 테스트 통과 확인**

Run:
```bash
pytest tests/unit/test_lessonplan_analysis_service.py -v
```

Expected: 새 테스트 PASS, 기존 `test_build_analysis_prompt` 포함 모든 케이스 PASS.

- [ ] **Step 2-5: 커밋**

```bash
git add app/services/lessonplan_analysis_service.py tests/unit/test_lessonplan_analysis_service.py
git commit -m "refactor(lesson-analysis): drop {model_name} substitution in prompt builder

프롬프트 헤더에서 모델 식별자 노출 제거의 일부. 빌더는 더 이상
self.model_name 을 system prompt 본문에 끼워넣지 않는다.

Refs: #82"
```

---

## Task 3: 후처리에 모델명 줄 제거 안전망 추가

**Files:**
- Modify: `app/services/lessonplan_analysis_service.py` (`_post_process_report` 본문 앞)
- Test: `tests/unit/test_lessonplan_analysis_service.py`

**Goal:** LLM이 학습 패턴으로 `> - **분석 모델**: ...` 줄을 자체적으로 생성할 가능성을 차단. 후처리 함수의 가장 앞에 1회 정규식 치환을 추가한다.

- [ ] **Step 3-1: 실패 테스트 작성**

`tests/unit/test_lessonplan_analysis_service.py`에 추가:

```python
    def test_post_process_strips_stray_model_line(self, service):
        """LLM 이 학습된 양식으로 `**분석 모델**:` 줄을 출력해도 후처리가 제거한다."""
        raw = (
            "# 수업 지도안 평가 보고서\n\n"
            "> **분석 개요**\n"
            "> - **분석 일시**: 2026-05-27 12:34\n"
            "> - **분석 모델**: gemini-2.5-flash\n"
            "\n"
            "## 1. 교육과정 목표 및 성격과의 부합\n"
            "본문\n"
        )

        processed = service._post_process_report(raw)

        # 모델명 줄이 제거된다
        assert "**분석 모델**" not in processed
        assert "gemini-2.5-flash" not in processed
        # 인접한 다른 헤더 라인은 보존
        assert "**분석 개요**" in processed
        assert "**분석 일시**" in processed
        assert "2026-05-27 12:34" in processed
        assert "## 1. 교육과정 목표 및 성격과의 부합" in processed
```

- [ ] **Step 3-2: 테스트 실패 확인**

Run:
```bash
pytest tests/unit/test_lessonplan_analysis_service.py::TestLessonPlanAnalysisService::test_post_process_strips_stray_model_line -v
```

Expected: FAIL — `**분석 모델**` 라인이 그대로 남아 첫 assertion에서 실패.

- [ ] **Step 3-3: 후처리 함수 시작부에 정규식 제거 단계 추가**

`app/services/lessonplan_analysis_service.py`의 `_post_process_report` 진입 부분(`import re` 이후, 기존 `try:` 블록 안쪽)에 다음을 추가. 위치: 기존 "Vector Search 참고 자료" 처리 직전.

```python
        import re

        try:
            # 0) LLM 이 학습된 양식으로 출력했을 수 있는 모델명 라인 제거.
            #    형태: `> - **분석 모델**: <임의 텍스트>` (전후 공백 허용)
            report = re.sub(
                r'^\s*>\s*-\s*\*\*분석\s*모델\*\*\s*:.*$\n?',
                '',
                report,
                flags=re.MULTILINE,
            )

            # 1) "Vector Search 참고 자료" 섹션 가독성 개선
            # ... (이하 기존 코드 그대로)
```

기존 함수의 `try` 블록 안 첫 줄(`# 1) "Vector Search 참고 자료" 섹션 가독성 개선`) 바로 앞에 0) 단계로 끼워넣는다.

- [ ] **Step 3-4: 테스트 + 회귀 확인**

Run:
```bash
pytest tests/unit/test_lessonplan_analysis_service.py -v
```

Expected: 새 테스트 PASS, 기존 모든 케이스 PASS.

- [ ] **Step 3-5: 커밋**

```bash
git add app/services/lessonplan_analysis_service.py tests/unit/test_lessonplan_analysis_service.py
git commit -m "feat(lesson-analysis): strip stray model-name line in post-processing

LLM 이 학습된 양식으로 \`> - **분석 모델**: ...\` 줄을 자체 생성하더라도
보고서에서 제거되도록 후처리 시작부에 정규식 제거 단계 추가.

Refs: #82"
```

---

## Task 4: `_collect_active_criteria_display_names` 헬퍼 추가

**Files:**
- Modify: `app/services/lessonplan_analysis_service.py` (헬퍼 추가)
- Test: `tests/unit/test_lessonplan_analysis_service.py`

**Goal:** alias_map의 active 항목에서 표시 이름(alias) 목록을 정렬해 반환하는 헬퍼. alias가 None/빈 항목은 제외하고 로그로 경고. fetch 실패 시 빈 리스트 반환 (예외 안 던짐).

- [ ] **Step 4-1: 실패 테스트 작성**

`tests/unit/test_lessonplan_analysis_service.py`에 추가:

```python
    @pytest.mark.asyncio
    async def test_collect_active_criteria_display_names_sorted(
        self, service
    ):
        """active 항목들의 alias 가 activated_at desc, stable_id desc 로 정렬되어 반환된다."""
        from app.schemas.alias_map import AliasMap, AliasMapEntry

        alias_map = AliasMap(
            schema_version=1,
            updated_at="2026-05-27T00:00:00Z",
            entries={
                "01OLDER": AliasMapEntry(
                    alias="구버전 기준",
                    status="active",
                    activated_at="2026-05-20T00:00:00Z",
                ),
                "01NEWER": AliasMapEntry(
                    alias="최신 기준",
                    status="active",
                    activated_at="2026-05-25T00:00:00Z",
                ),
                "01INACTIVE": AliasMapEntry(
                    alias="비활성",
                    status="uploaded",
                    activated_at=None,
                ),
            },
        )

        with patch(
            "app.services.criteria_alias_map_service"
            ".CriteriaAliasMapService.fetch",
            new=AsyncMock(return_value=("doc/name", alias_map)),
        ):
            names = await service._collect_active_criteria_display_names()

        assert names == ["최신 기준", "구버전 기준"]

    @pytest.mark.asyncio
    async def test_collect_active_criteria_display_names_skips_missing_alias(
        self, service, caplog
    ):
        """alias 가 None/빈 문자열인 active 항목은 결과에서 제외되고 경고 로그가 남는다."""
        from app.schemas.alias_map import AliasMap, AliasMapEntry

        alias_map = AliasMap(
            schema_version=1,
            updated_at="2026-05-27T00:00:00Z",
            entries={
                "01ALIASNONE": AliasMapEntry(
                    alias=None,
                    status="active",
                    activated_at="2026-05-25T00:00:00Z",
                ),
                "01EMPTY": AliasMapEntry(
                    alias="",
                    status="active",
                    activated_at="2026-05-24T00:00:00Z",
                ),
                "01OK": AliasMapEntry(
                    alias="정상 alias",
                    status="active",
                    activated_at="2026-05-23T00:00:00Z",
                ),
            },
        )

        with patch(
            "app.services.criteria_alias_map_service"
            ".CriteriaAliasMapService.fetch",
            new=AsyncMock(return_value=("doc/name", alias_map)),
        ):
            with caplog.at_level("WARNING"):
                names = await service._collect_active_criteria_display_names()

        assert names == ["정상 alias"]
        assert any(
            "alias 누락" in record.message
            or "alias missing" in record.message.lower()
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_collect_active_criteria_display_names_fetch_failure(
        self, service
    ):
        """fetch 가 예외를 던지면 빈 리스트를 반환하고 예외를 전파하지 않는다."""
        with patch(
            "app.services.criteria_alias_map_service"
            ".CriteriaAliasMapService.fetch",
            new=AsyncMock(side_effect=RuntimeError("network down")),
        ):
            names = await service._collect_active_criteria_display_names()

        assert names == []
```

- [ ] **Step 4-2: 테스트 실패 확인**

Run:
```bash
pytest tests/unit/test_lessonplan_analysis_service.py -k collect_active_criteria_display_names -v
```

Expected: 3개 테스트 모두 FAIL — `AttributeError: ... has no attribute '_collect_active_criteria_display_names'`.

- [ ] **Step 4-3: 헬퍼 메서드 구현**

`app/services/lessonplan_analysis_service.py`의 `LessonPlanAnalysisService` 클래스에 추가 (다른 헬퍼들 근처, 예: `_extract_citations` 위):

```python
    async def _collect_active_criteria_display_names(self) -> list[str]:
        """활성 평가기준의 표시 이름(alias)을 정렬해 반환한다.

        정렬: activated_at 내림차순, stable_id 내림차순 (CriteriaVectorService
        ._get_active_stable_ids 와 동일한 정책).

        alias 가 None/빈 항목은 결과에서 제외하고 경고 로그를 남긴다.
        alias_map fetch 자체가 실패하면 빈 리스트를 반환하고 예외를 전파하지 않는다.
        """
        from app.services.criteria_alias_map_service import (
            CriteriaAliasMapService,
        )
        from app.services.criteria_reconciliation_service import (
            is_legacy_surrogate_stable_id,
        )

        try:
            alias_svc = CriteriaAliasMapService(
                client=self.client,
                store_display_name=settings.FS_RUBRIC_STORE_NAME,
            )
            fetched = await alias_svc.fetch()
        except Exception as exc:
            logger.warning(
                f"활성 평가기준 alias 목록 조회 실패 (참고 문서 표시 생략): {exc}"
            )
            return []

        if not fetched:
            return []

        _, alias_map = fetched

        active_entries = [
            (stable_id, entry)
            for stable_id, entry in alias_map.entries.items()
            if (
                entry.status == "active"
                and not is_legacy_surrogate_stable_id(stable_id)
            )
        ]

        active_entries.sort(
            key=lambda item: (item[1].activated_at or "", item[0]),
            reverse=True,
        )

        names: list[str] = []
        for stable_id, entry in active_entries:
            alias = (entry.alias or "").strip()
            if not alias:
                logger.warning(
                    f"활성 평가기준 alias 누락: stable_id={stable_id} "
                    "(보고서 참고 문서 목록에서 제외)"
                )
                continue
            names.append(alias)
        return names
```

- [ ] **Step 4-4: 테스트 통과 확인**

Run:
```bash
pytest tests/unit/test_lessonplan_analysis_service.py -k collect_active_criteria_display_names -v
```

Expected: 3개 테스트 모두 PASS.

회귀 확인:
```bash
pytest tests/unit/test_lessonplan_analysis_service.py -v
```

Expected: 모든 케이스 PASS.

- [ ] **Step 4-5: 커밋**

```bash
git add app/services/lessonplan_analysis_service.py tests/unit/test_lessonplan_analysis_service.py
git commit -m "feat(lesson-analysis): add helper to collect active criteria display names

alias_map 의 active 항목에서 alias 목록을 activated_at 내림차순으로 정렬해
반환. fetch 실패는 빈 리스트로 흡수하고 alias 누락 항목은 경고 후 제외.

Refs: #82"
```

---

## Task 5: `_render_file_search_references_section` 헬퍼 추가

**Files:**
- Modify: `app/services/lessonplan_analysis_service.py`
- Test: `tests/unit/test_lessonplan_analysis_service.py`

**Goal:** 활성 평가기준 alias 목록과 수업지도안 원본 파일명을 받아 `### File Search 참고 문서` 섹션 본문 마크다운을 생성하는 순수 함수.

- [ ] **Step 5-1: 실패 테스트 작성**

`tests/unit/test_lessonplan_analysis_service.py`에 추가:

```python
    def test_render_file_search_references_full(self, service):
        """평가기준 alias + 수업지도안 파일명이 모두 있으면 항목 3개를 반환한다."""
        rendered = service._render_file_search_references_section(
            criteria_aliases=["A 기준", "B 기준"],
            lessonplan_original_filename="우리반 수업계획.pdf",
        )
        assert rendered == (
            "- A 기준\n"
            "- B 기준\n"
            "- 우리반 수업계획.pdf"
        )

    def test_render_file_search_references_only_criteria(self, service):
        """수업지도안 파일명이 없으면 평가기준만 표시한다."""
        rendered = service._render_file_search_references_section(
            criteria_aliases=["A 기준"],
            lessonplan_original_filename=None,
        )
        assert rendered == "- A 기준"

    def test_render_file_search_references_only_lessonplan(self, service):
        """평가기준 alias 가 비어도 수업지도안 파일명만 표시한다."""
        rendered = service._render_file_search_references_section(
            criteria_aliases=[],
            lessonplan_original_filename="lesson.pdf",
        )
        assert rendered == "- lesson.pdf"

    def test_render_file_search_references_empty(self, service):
        """둘 다 비면 placeholder 를 반환한다."""
        rendered = service._render_file_search_references_section(
            criteria_aliases=[],
            lessonplan_original_filename=None,
        )
        assert rendered == "(표시할 항목이 없습니다)"
```

- [ ] **Step 5-2: 테스트 실패 확인**

Run:
```bash
pytest tests/unit/test_lessonplan_analysis_service.py -k render_file_search_references -v
```

Expected: 4개 테스트 모두 FAIL — `AttributeError`.

- [ ] **Step 5-3: 헬퍼 구현**

`app/services/lessonplan_analysis_service.py`의 `LessonPlanAnalysisService` 클래스에 추가 (`_collect_active_criteria_display_names` 근처):

```python
    @staticmethod
    def _render_file_search_references_section(
        criteria_aliases: list[str],
        lessonplan_original_filename: Optional[str],
    ) -> str:
        """### File Search 참고 문서 섹션의 본문(헤더 제외) 마크다운을 생성한다.

        - 활성 평가기준 표시 이름들 (이미 정렬됨)
        - 수업 지도안 원본 파일명 (있을 경우)
        둘 다 비면 placeholder 반환.
        """
        items: list[str] = list(criteria_aliases)
        if lessonplan_original_filename:
            items.append(lessonplan_original_filename)
        if not items:
            return "(표시할 항목이 없습니다)"
        return "\n".join(f"- {item}" for item in items)
```

- [ ] **Step 5-4: 테스트 통과 + 회귀 확인**

Run:
```bash
pytest tests/unit/test_lessonplan_analysis_service.py -v
```

Expected: 모든 케이스 PASS.

- [ ] **Step 5-5: 커밋**

```bash
git add app/services/lessonplan_analysis_service.py tests/unit/test_lessonplan_analysis_service.py
git commit -m "feat(lesson-analysis): add renderer for File Search 참고 문서 section body

활성 평가기준 alias 와 수업지도안 원본 파일명을 입력으로 받아 결정론적
마크다운 목록을 생성. 빈 입력은 placeholder 로 처리.

Refs: #82"
```

---

## Task 6: `_post_process_report`에 섹션 치환 단계 추가

**Files:**
- Modify: `app/services/lessonplan_analysis_service.py` (`_post_process_report` 시그니처 + 본문)
- Test: `tests/unit/test_lessonplan_analysis_service.py`

**Goal:** `_post_process_report`가 옵션 인자 `criteria_aliases`와 `lessonplan_original_filename`을 받도록 시그니처 확장. 인자 데이터가 있으면 보고서에서 `### File Search 참고 문서` 섹션 본문을 서버 렌더로 교체. 섹션이 없으면 보고서 끝에 부착. 인자가 모두 None/빈 이면 이 단계는 건너뜀 (기존 테스트와의 호환성 유지).

- [ ] **Step 6-1: 실패 테스트 작성 (섹션 검출/치환)**

`tests/unit/test_lessonplan_analysis_service.py`에 추가:

```python
    def test_post_process_replaces_file_search_section(self, service):
        """LLM 이 생성한 `### File Search 참고 문서` 본문이 서버 렌더로 교체된다."""
        raw = (
            "## 종합 평가\n\n"
            "요약 본문\n\n"
            "### File Search 참고 문서\n"
            "- LLM 이 적은 임의의 문서 제목\n"
            "- 또 다른 임의 항목\n"
        )

        processed = service._post_process_report(
            raw,
            criteria_aliases=["정보 교육과정 평가기준"],
            lessonplan_original_filename="수업안.pdf",
        )

        # 서버 렌더 항목이 등장한다
        assert "- 정보 교육과정 평가기준" in processed
        assert "- 수업안.pdf" in processed
        # LLM 이 적은 임의 항목은 사라진다
        assert "LLM 이 적은 임의의 문서 제목" not in processed
        assert "또 다른 임의 항목" not in processed
        # 헤더는 보존된다
        assert "### File Search 참고 문서" in processed
        # 이전 섹션도 보존
        assert "## 종합 평가" in processed
        assert "요약 본문" in processed

    def test_post_process_appends_file_search_section_when_missing(
        self, service
    ):
        """보고서에 섹션이 없으면 끝에 부착한다."""
        raw = (
            "## 종합 평가\n\n"
            "요약 본문\n"
        )

        processed = service._post_process_report(
            raw,
            criteria_aliases=["A 기준"],
            lessonplan_original_filename="lesson.pdf",
        )

        assert "### File Search 참고 문서" in processed
        assert "- A 기준" in processed
        assert "- lesson.pdf" in processed
        # 부착되어도 이전 본문은 보존
        assert "## 종합 평가" in processed

    def test_post_process_keeps_legacy_signature(self, service):
        """기존 호출 형태(인자 미제공)는 그대로 작동하여 회귀가 없다."""
        raw = (
            "## 종합 평가\n\n"
            "요약 본문\n\n"
            "### File Search 참고 문서\n"
            "- LLM 이 적은 임의 항목\n"
        )

        processed = service._post_process_report(raw)

        # 인자가 없으면 섹션 치환 단계가 건너뛰어진다 → LLM 출력 유지
        assert "LLM 이 적은 임의 항목" in processed
```

- [ ] **Step 6-2: 테스트 실패 확인**

Run:
```bash
pytest tests/unit/test_lessonplan_analysis_service.py -k "replaces_file_search_section or appends_file_search_section or keeps_legacy_signature" -v
```

Expected: `replaces_file_search_section`, `appends_file_search_section` FAIL (인자 미지원), `keeps_legacy_signature` PASS (현재 시그니처와 동일).

- [ ] **Step 6-3: 시그니처 확장 + 치환 단계 추가**

`app/services/lessonplan_analysis_service.py`의 `_post_process_report`를 다음과 같이 수정:

```python
    def _post_process_report(
        self,
        report: str,
        criteria_aliases: Optional[list[str]] = None,
        lessonplan_original_filename: Optional[str] = None,
    ) -> str:
        """
        보고서 후처리:
        0. `**분석 모델**:` 줄 제거 (Task 3 에서 추가됨)
        1. 'Vector Search 참고 자료' 섹션이 비구조화된 긴 텍스트일 경우 목록으로 정리
        2. 'File Search 참고 문서' 섹션을 서버 렌더로 교체 (인자 제공 시).
           섹션이 없으면 보고서 끝에 부착.
        3. 본문 전체에서 이모지/픽토그램 제거

        Args:
            report: 원본 Markdown 보고서
            criteria_aliases: 활성 평가기준 표시 이름 목록 (정렬 완료)
            lessonplan_original_filename: 분석 대상 수업지도안 원본 파일명
        """
        import re

        try:
            # 0) 모델명 라인 제거 (Task 3)
            report = re.sub(
                r'^\s*>\s*-\s*\*\*분석\s*모델\*\*\s*:.*$\n?',
                '',
                report,
                flags=re.MULTILINE,
            )

            # 1) "Vector Search 참고 자료" 섹션 가독성 개선 (기존)
            # ... (기존 코드 그대로)

            # 2) "File Search 참고 문서" 섹션을 서버 렌더로 교체
            should_render_refs = (
                criteria_aliases is not None
                or lessonplan_original_filename is not None
            )
            if should_render_refs:
                body = self._render_file_search_references_section(
                    criteria_aliases=criteria_aliases or [],
                    lessonplan_original_filename=(
                        lessonplan_original_filename
                    ),
                )
                refs_pattern = (
                    r'(###\s*(?:[^\n]*?)?File Search 참고 문서\s*\n)'
                    r'(.*?)(\n###|\Z)'
                )
                refs_match = re.search(
                    refs_pattern, report, flags=re.DOTALL
                )
                if refs_match:
                    header = refs_match.group(1)
                    next_section = refs_match.group(3)
                    new_section = f"{header}{body}\n{next_section}"
                    report = (
                        report[: refs_match.start()]
                        + new_section
                        + report[refs_match.end():]
                    )
                else:
                    # 섹션이 누락된 경우 끝에 부착
                    suffix = (
                        "\n\n### File Search 참고 문서\n"
                        f"{body}\n"
                    )
                    if not report.endswith("\n"):
                        report += "\n"
                    report += suffix

            # 3) 본문 이모지 제거 (기존)
            report = self._sanitize_report_lines(report)

            return report
        # ... (기존 except 블록 그대로)
```

**중요:** 기존의 `# 1)` 블록 전체를 보존하고, 그 뒤에 `# 2)` 블록을 추가한다. 기존의 `# 2)` (이모지 제거) 주석은 `# 3)`으로 번호만 갱신. 본문 코드는 변경하지 않음.

**Import 보강:** 파일 상단의 `from typing import Any, Dict, Optional` 은 이미 `Optional`을 포함하므로 추가 import 불필요.

- [ ] **Step 6-4: 테스트 통과 + 회귀 확인**

Run:
```bash
pytest tests/unit/test_lessonplan_analysis_service.py -v
```

Expected: 모든 케이스 PASS. 특히 기존 `_post_process_report` 회귀 케이스 전부 PASS여야 함.

`tests/test_lessonplan_analysis_service.py` (구버전 테스트 파일)도 한번 돌려서 회귀 없는지 확인:

```bash
pytest tests/test_lessonplan_analysis_service.py -v
```

Expected: 모든 케이스 PASS.

- [ ] **Step 6-5: 커밋**

```bash
git add app/services/lessonplan_analysis_service.py tests/unit/test_lessonplan_analysis_service.py
git commit -m "feat(lesson-analysis): replace File Search 참고 문서 section with server-rendered list

후처리에 옵션 인자 추가: criteria_aliases, lessonplan_original_filename.
인자가 제공되면 LLM 이 생성한 섹션 본문을 서버 렌더로 교체. 섹션이
누락된 경우 보고서 끝에 부착. 인자 미제공 시 기존 동작 유지(회귀 없음).

Refs: #82"
```

---

## Task 7: `analyze_lesson_plan`에서 새 데이터 수집 후 후처리에 전달

**Files:**
- Modify: `app/services/lessonplan_analysis_service.py` (`analyze_lesson_plan` 본문)
- Test: `tests/unit/test_lessonplan_analysis_service.py`

**Goal:** 분석 흐름 본체에서 (a) 활성 평가기준 alias 목록 수집, (b) 수업지도안 원본 파일명 결정, (c) `_post_process_report`에 전달.

**현재 흐름 (lessonplan_analysis_service.py:264):**

```python
raw_report = response.text if response.text else ""
report = self._post_process_report(raw_report)
```

**위치 결정:** `original_filename`은 현재 line 279~300 사이에서 결정된다. post-process 이전에 필요하므로 그 결정 로직을 헬퍼로 추출하여 post-process 이전에 1회 호출.

- [ ] **Step 7-1: 원본 파일명 결정 헬퍼 + 단위 테스트 작성 (실패)**

`tests/unit/test_lessonplan_analysis_service.py`에 추가:

```python
    def test_resolve_lessonplan_original_filename_from_upload(self, service):
        """latest_upload 가 있으면 그것의 original_filename 을 반환한다."""
        upload = Mock()
        upload.original_filename = "수업안.pdf"
        result = service._resolve_lessonplan_original_filename(
            latest_upload=upload,
            legacy_lessonplans=[],
        )
        assert result == "수업안.pdf"

    def test_resolve_lessonplan_original_filename_from_legacy(self, service):
        """latest_upload 가 None 이면 legacy 목록 중 최신 항목 사용."""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        legacy = [
            {
                "original_filename": "old.pdf",
                "filename": "x_old.pdf",
                "created_at": now - timedelta(days=1),
            },
            {
                "original_filename": "new.pdf",
                "filename": "x_new.pdf",
                "created_at": now,
            },
        ]
        result = service._resolve_lessonplan_original_filename(
            latest_upload=None,
            legacy_lessonplans=legacy,
        )
        assert result == "new.pdf"

    def test_resolve_lessonplan_original_filename_none(self, service):
        """둘 다 없으면 None 반환."""
        result = service._resolve_lessonplan_original_filename(
            latest_upload=None,
            legacy_lessonplans=[],
        )
        assert result is None
```

- [ ] **Step 7-2: 테스트 실패 확인**

Run:
```bash
pytest tests/unit/test_lessonplan_analysis_service.py -k resolve_lessonplan_original_filename -v
```

Expected: 3개 FAIL — `AttributeError`.

- [ ] **Step 7-3: 헬퍼 구현**

`app/services/lessonplan_analysis_service.py`에 추가:

```python
    @staticmethod
    def _resolve_lessonplan_original_filename(
        latest_upload,
        legacy_lessonplans: list,
    ) -> Optional[str]:
        """분석 대상 수업지도안의 원본 파일명을 결정한다.

        - latest_upload 가 있으면 그 original_filename
        - 없으면 legacy_lessonplans 중 created_at 최댓값 항목의 original_filename
        - 둘 다 없으면 None
        """
        if latest_upload is not None:
            return getattr(latest_upload, "original_filename", None)
        if legacy_lessonplans:
            latest = max(
                legacy_lessonplans, key=lambda x: x["created_at"]
            )
            return latest.get("original_filename")
        return None
```

- [ ] **Step 7-4: 헬퍼 테스트 통과 확인**

Run:
```bash
pytest tests/unit/test_lessonplan_analysis_service.py -k resolve_lessonplan_original_filename -v
```

Expected: 3개 PASS.

- [ ] **Step 7-5: `analyze_lesson_plan` 본문에서 후처리 호출 변경**

`app/services/lessonplan_analysis_service.py:262-264` 부근 수정. 현재:

```python
# 4. Markdown 보고서 추출 및 후처리
raw_report = response.text if response.text else ""
report = self._post_process_report(raw_report)  # 후처리 적용
```

다음으로 변경:

```python
# 4. Markdown 보고서 추출 및 후처리
raw_report = response.text if response.text else ""
criteria_aliases = (
    await self._collect_active_criteria_display_names()
)
lessonplan_original_filename = (
    self._resolve_lessonplan_original_filename(
        latest_upload=latest_upload,
        legacy_lessonplans=legacy_lessonplans,
    )
)
report = self._post_process_report(
    raw_report,
    criteria_aliases=criteria_aliases,
    lessonplan_original_filename=lessonplan_original_filename,
)
```

**주의:** 이 시점에 `legacy_lessonplans`가 항상 정의되어 있어야 한다. 현재 코드에서는 `latest_upload is None` 분기 안에서만 정의되고 그 외에는 `legacy_lessonplans = []`로 초기화된 상태(line 178). 그대로 활용 가능.

- [ ] **Step 7-6: 분석 흐름 통합 테스트 (모킹된 Gemini)**

`tests/unit/test_lessonplan_analysis_service.py` 의 `test_analyze_lesson_plan_success` 를 확장하거나 새 케이스 추가:

```python
    @pytest.mark.asyncio
    async def test_analyze_lesson_plan_writes_server_rendered_refs(
        self, service
    ):
        """분석 결과 보고서에 서버 렌더 참고 문서 섹션이 포함되고 모델명은 노출되지 않는다."""
        from app.schemas.alias_map import AliasMap, AliasMapEntry

        # store 조회
        service._get_store_ids = AsyncMock(
            return_value=["user-store", "rubric-store"]
        )

        # 활성 평가기준 metadata filter — 존재한다고 가정
        with patch(
            "app.services.criteria_vector_service"
            ".CriteriaVectorService.active_stable_id_filter",
            new=AsyncMock(return_value='stable_id="X"'),
        ), patch(
            "app.services.criteria_alias_map_service"
            ".CriteriaAliasMapService.fetch",
            new=AsyncMock(
                return_value=(
                    "doc/name",
                    AliasMap(
                        schema_version=1,
                        updated_at="2026-05-27T00:00:00Z",
                        entries={
                            "01OK": AliasMapEntry(
                                alias="정보 교육과정 평가기준",
                                status="active",
                                activated_at="2026-05-25T00:00:00Z",
                            ),
                        },
                    ),
                )
            ),
        ):
            service.prompt_loader.get_prompt = Mock(
                return_value="lesson_analysis prompt"
            )
            mock_response = Mock()
            mock_response.text = (
                "# 보고서\n\n"
                "> **분석 모델**: secret-internal-model\n\n"
                "## 종합 평가\n본문\n\n"
                "### File Search 참고 문서\n- 임의 항목\n"
            )
            mock_response.candidates = []
            service.client.models.generate_content = Mock(
                return_value=mock_response
            )

            # 분석 흐름의 보고서 저장/DB 기록 부분은 본 테스트의 관심사 밖이므로
            # 적절히 모킹하거나 기존 success 케이스 전략을 재사용한다.
            service._find_existing_report_for_latest_upload = AsyncMock(
                return_value=(None, None)
            )
            service._user_file_search_store_has_documents = Mock(
                return_value=True
            )

            result = await service.analyze_lesson_plan(
                session_id=1,
                user_id=123,
                username="alice",
            )

        assert result["success"] is True
        report = result["report"]
        assert "정보 교육과정 평가기준" in report
        assert "secret-internal-model" not in report
        assert "**분석 모델**" not in report
        assert "임의 항목" not in report
```

이 테스트는 store / DB / 파일 저장 등 부수 효과 다수에 영향을 받는다. 기존 `test_analyze_lesson_plan_success`의 모킹 패턴을 그대로 따라 시작하고, 보고서 저장 분기가 실패해도 `success: True`/`report` 부분만 검증하도록 한다.

**테스트가 너무 깊은 모킹을 요구한다면**: 본 케이스는 통합 테스트로 분리하지 말고 핵심 가정만 확인하는 단위 테스트로 유지한다. 보고서 내용만 보면 되므로 DB/저장 모킹은 다음과 같이 단순화:

```python
# DB 저장 분기 진입을 막기 위해 latest_upload 가 없는 legacy 경로 활용
service.lessonplan_storage.list_lessonplans = Mock(return_value=[])
service._user_file_search_store_has_documents = Mock(return_value=True)
```

여기서 `report_storage.save_report` 호출이 디스크를 건드리는지 확인. 만약 그렇다면 `service.report_storage.save_report = Mock(return_value={"filename":"x","file_path":"/tmp/x"})` 로 모킹.

- [ ] **Step 7-7: 테스트 실패 확인**

Run:
```bash
pytest tests/unit/test_lessonplan_analysis_service.py::TestLessonPlanAnalysisService::test_analyze_lesson_plan_writes_server_rendered_refs -v
```

Expected: 처음에는 아직 Step 7-5의 변경이 안 됐을 수도 있고, 모킹 누락으로 실패할 수 있음. 실패 메시지 보고 다음 단계로.

- [ ] **Step 7-8: Step 7-5의 코드 변경 적용 (아직 안 됐다면)**

Step 7-5에 명시된 `analyze_lesson_plan` 본문 변경을 적용. 적용된 후:

Run:
```bash
pytest tests/unit/test_lessonplan_analysis_service.py -v
```

Expected: 새 테스트 PASS, 기존 테스트 회귀 없음.

만약 새 테스트가 여전히 실패하면, 모킹 누락 라인을 그때 보고 보완. **자기 합리화 금지**: 테스트가 본 작업의 핵심 통합 검증이므로 통과해야 한다.

- [ ] **Step 7-9: 커밋**

```bash
git add app/services/lessonplan_analysis_service.py tests/unit/test_lessonplan_analysis_service.py
git commit -m "feat(lesson-analysis): wire active aliases + filename into post-processing

analyze_lesson_plan 에서 활성 평가기준 alias 와 수업지도안 원본 파일명을
계산해 _post_process_report 에 전달. 통합 단위 테스트로 보고서 출력이
서버 렌더 참고문서와 모델명 미노출을 모두 만족하는지 검증.

Refs: #82
Closes: #82"
```

---

## Task 8: 수동 검증 및 전체 회귀 테스트

**Files:** (코드 변경 없음)

**Goal:** 자동 테스트 외 수동 시나리오로 실제 동작 확인.

- [ ] **Step 8-1: 전체 테스트 스위트 실행**

Run:
```bash
pytest tests/ -x -q
```

Expected: 모든 테스트 PASS. 실패가 있으면 본 변경과 무관한 기존 결함인지 확인 후 보고.

- [ ] **Step 8-2: ruff lint 통과 확인**

Run:
```bash
ruff check app/services/lessonplan_analysis_service.py tests/unit/test_lessonplan_analysis_service.py
```

Expected: `All checks passed!`

수정이 필요하면 `ruff check --fix` 또는 수동 정리 후 커밋 추가.

- [ ] **Step 8-3: 수동 시나리오 가이드 (코드 검증 단계 아님 — 운영자가 수행)**

본 step은 실행 명령이 아닌 PR description 또는 issue 코멘트에 적을 시나리오 안내. 다음 항목을 PR/이슈에 적는다:

```
수동 검증 시나리오:

1. 평가기준 2개 활성화 (관리자 패널에서 토글 ON)
2. 사용자 계정으로 수업지도안 업로드 후 분석 실행
3. 생성된 보고서 확인:
   - 보고서 헤더에 '**분석 모델**: ...' 줄이 없는지
   - '### File Search 참고 문서' 섹션 항목이:
     * 활성 평가기준 2개의 표시 이름
     * 업로드한 수업지도안의 원본 파일명
     으로 구성되는지
4. 평가기준 1개를 OFF로 토글 후 다시 분석 (다른 수업지도안 업로드)
5. 새 보고서의 참고 문서 섹션에 OFF 시킨 항목이 사라졌는지 확인
```

- [ ] **Step 8-4: 최종 정리 커밋 (필요 시)**

lint/포맷 수정이 있으면 별도 커밋:

```bash
git add -p
git commit -m "style(lesson-analysis): post-implementation lint cleanup

Refs: #82"
```

없으면 본 step 생략.

---

## 자체 검토 (작성자 메모)

**스펙 커버리지 확인:**

스펙 § 3.1 흐름 (모델명 줄 제거 → Vector Search 정리 → File Search 치환 → 살균) → Task 1/2/3/6에서 구현.
스펙 § 3.2 데이터 소스 (alias_map active + original_filename) → Task 4/7에서 수집.
스펙 § 3.3 새 헬퍼 두 개 → Task 4, 5.
스펙 § 3.4 후처리 변경 + 정규식 패턴 → Task 6.
스펙 § 3.5 모델명 제거 (프롬프트 + 코드 + 안전망) → Task 1/2/3.
스펙 § 3.6 동작 매트릭스 → Task 5/6/7 의 단위/통합 테스트로 커버.
스펙 § 5.1 단위 테스트 항목 → Task 4/5/6/7에서 각각 작성.
스펙 § 5.2 통합 테스트 1 케이스 → Task 7-6.
스펙 § 5.3 수동 검증 → Task 8-3.

**Placeholder 스캔:** 본 문서에 TBD/TODO/"implement later" 없음. 모든 스텝에 실제 코드/명령 포함.

**타입 일관성:**
- `_collect_active_criteria_display_names() -> list[str]` — 일관됨
- `_render_file_search_references_section(criteria_aliases: list[str], lessonplan_original_filename: Optional[str]) -> str` — 일관됨
- `_resolve_lessonplan_original_filename(latest_upload, legacy_lessonplans: list) -> Optional[str]` — 일관됨
- `_post_process_report(report: str, criteria_aliases: Optional[list[str]] = None, lessonplan_original_filename: Optional[str] = None) -> str` — 일관됨

**호환성 검토:** `_post_process_report`의 새 인자는 모두 Optional 기본값. 기존 테스트 호출(인자 없이)이 그대로 작동. 새 호출(production analyze_lesson_plan)만 인자를 전달.
