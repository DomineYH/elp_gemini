# Fix 429 RESOURCE_EXHAUSTED on Lesson Plan Analysis

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task.

**Goal:** Eliminate the `429 RESOURCE_EXHAUSTED — Failed to embed content` failure that surfaces when a user uploads a PDF and clicks "분석하기", and give the API a graceful, user-friendly recovery path when the underlying Gemini quota is genuinely exhausted.

**Architecture:** Two layers of fix — (1) reduce the number of embedding-backed File Search calls per analysis from 2+ down to 1 by removing a redundant pre-fetch, and (2) wrap the remaining Gemini call in a 429-aware exponential-backoff retry. Surface the post-retry failure to the client as HTTP 429 with a clear, localized "retry shortly" message instead of a generic 500.

**Tech Stack:** FastAPI · google-genai SDK · tenacity (already vendored) · pytest

---

## Background

### Symptom

When a user uploads a PDF and clicks "분석하기", the server logs:

```
google.genai.errors.ClientError: 429 RESOURCE_EXHAUSTED.
{'error': {'code': 429, 'message': 'Failed to embed content.', 'status': 'RESOURCE_EXHAUSTED'}}
```

Traceback ends at `app/services/lessonplan_analysis_service.py:108` — the main `client.models.generate_content(...)` call that uses the `file_search` tool against the rubric + user stores.

### Root Cause

The 429 error body is `"Failed to embed content."`. This is the Gemini File Search tool's embedding sub-system telling us the embedding-tier quota for the configured model is exhausted. Three reinforcing causes:

1. **Two embedding-backed calls per analyze.** Step 1 of `analyze_lesson_plan` calls `_get_criteria_context()` → `CriteriaVectorService.search_criteria()` → `FileSearchService.search_in_store()` → `generate_content(..., file_search=...)` on `rubricstore` (1 embedding op). Step 4 then makes the *main* `generate_content` call with File Search on **both** `rubric_store_id` and `user_store_id` (≥ 1 more embedding op). So a single analyze click triggers 2+ embedding queries back-to-back. (`app/services/lessonplan_analysis_service.py:76-121`)

2. **Pre-fetch is redundant.** The main call already retrieves from `rubricstore` via the File Search tool, so the Step 1 pre-fetch is duplicate work — it doubles embedding-quota burn without adding signal the main model doesn't already have. (`app/services/lessonplan_analysis_service.py:108-121`, see the `file_search_store_names=[rubric_store_id, user_store_id]` argument)

3. **Preview model + no client-side retry.** `GEMINI_EVAL_MODEL` defaults to `gemini-3-flash-preview` (`app/config.py:65-68`). Preview models carry much tighter embedding quotas than stable releases. There is **no retry** on 429 anywhere in the call chain — the SDK's internal `tenacity` retries do not recover here because the quota is hard-exhausted, not transient. The exception bubbles up and the router maps it to a generic HTTP 500 with the message "분석 중 오류 발생". (`app/routers/lessonplan_analysis.py:55-69`)

### Why "Failed to embed content" appears for a `generate_content` call

The `file_search` tool implicitly embeds (a) the query (always) and, on store warmup paths, (b) document chunks. When this internal embedding call hits the per-model embedding-tier rate limit, the entire `generate_content` request fails with this exact body even though our code never directly called an `embed_content` endpoint.

### Why this is not a recent regression

`git log -- app/services/lessonplan_analysis_service.py` shows no edits in the last several commits; recent activity has been admin UI / criteria features. This is a baseline behavior that becomes visible whenever quota is tight or two analyses are run close together.

---

## Tasks

### Task 1: 429-aware retry helper

**Files:**
- Create: `app/utils/gemini_retry.py`
- Test: `tests/utils/test_gemini_retry.py` (create directory if missing)

**Step 1: Write the failing test**

```python
# tests/utils/test_gemini_retry.py
import pytest
from unittest.mock import MagicMock
from google.genai import errors as genai_errors

from app.utils.gemini_retry import retry_on_resource_exhausted, GeminiQuotaExhausted


def _make_429():
    # google-genai ClientError signature: (code, response_json, response)
    return genai_errors.ClientError(
        429,
        {"error": {"code": 429, "message": "Failed to embed content.",
                   "status": "RESOURCE_EXHAUSTED"}},
        MagicMock(),
    )


def test_retries_on_429_then_succeeds():
    calls = {"n": 0}

    @retry_on_resource_exhausted(max_attempts=3, initial_wait=0.0)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _make_429()
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3


def test_raises_gemini_quota_exhausted_after_max_attempts():
    @retry_on_resource_exhausted(max_attempts=2, initial_wait=0.0)
    def always_429():
        raise _make_429()

    with pytest.raises(GeminiQuotaExhausted):
        always_429()


def test_passes_through_non_429_errors():
    @retry_on_resource_exhausted(max_attempts=3, initial_wait=0.0)
    def boom():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        boom()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/utils/test_gemini_retry.py -x`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.utils.gemini_retry'`

**Step 3: Write minimal implementation**

```python
# app/utils/gemini_retry.py
"""
Gemini API retry helpers.

Wraps blocking Gemini SDK calls with exponential-backoff retry on
429 RESOURCE_EXHAUSTED. After max attempts, raises GeminiQuotaExhausted
so the caller can map it to HTTP 429 (instead of a generic 500).
"""
import functools
import logging
from typing import Callable, TypeVar

from google.genai import errors as genai_errors
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    RetryError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class GeminiQuotaExhausted(Exception):
    """Raised when 429 retries are exhausted."""


def _is_resource_exhausted(exc: BaseException) -> bool:
    if isinstance(exc, genai_errors.ClientError):
        code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        return code == 429
    return False


def retry_on_resource_exhausted(
    max_attempts: int = 3,
    initial_wait: float = 2.0,
    max_wait: float = 16.0,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator: retry the wrapped sync callable on Gemini 429 with
    exponential backoff (initial_wait, 2x, 4x ... capped at max_wait).
    """
    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> T:
            tenacity_retry = retry(
                retry=retry_if_exception(_is_resource_exhausted),
                stop=stop_after_attempt(max_attempts),
                wait=wait_exponential(
                    multiplier=initial_wait, max=max_wait
                ) if initial_wait > 0 else wait_exponential(multiplier=0, max=0),
                reraise=True,
            )
            try:
                return tenacity_retry(fn)(*args, **kwargs)
            except genai_errors.ClientError as e:
                if _is_resource_exhausted(e):
                    logger.error(
                        "Gemini 429 RESOURCE_EXHAUSTED after %d attempts: %s",
                        max_attempts, e,
                    )
                    raise GeminiQuotaExhausted(str(e)) from e
                raise
            except RetryError as e:  # safety: should not happen with reraise=True
                raise GeminiQuotaExhausted(str(e)) from e
        return wrapper
    return decorator
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/utils/test_gemini_retry.py -x`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add app/utils/gemini_retry.py tests/utils/test_gemini_retry.py
git commit -m "feat(gemini): add 429 retry helper with exponential backoff"
```

---

### Task 2: Eliminate redundant criteria pre-fetch

**Why:** The Step 1 Vector Search in `analyze_lesson_plan` re-queries `rubricstore`, but the Step 4 `generate_content` call already includes `rubricstore` in `file_search_store_names`. The pre-fetch doubles embedding-quota burn for no model-quality gain.

**Files:**
- Modify: `app/services/lessonplan_analysis_service.py` (remove Step 1 call and the `criteria_context` token in the prompt)

**Step 1: Update the analyze method**

Edit `analyze_lesson_plan` to drop the `_get_criteria_context()` call:

```python
# Before (lines ~75-77):
# 1. Vector Search (평가기준 컨텍스트)
criteria_context = await self._get_criteria_context()
logger.info("평가기준 컨텍스트 추출 완료")

# After:
# (removed — the main generate_content call below already retrieves
#  evaluation criteria via File Search over rubric_store_id.)
```

And update `_build_analysis_prompt` to no longer require / inject `criteria_context`. Drop the parameter and the `### [참고 자료: Vector Search로 검색된 평가기준 컨텍스트]` section from the prompt template; the rubric document is reached via File Search.

Keep `_get_criteria_context` and `CriteriaContextService` for now — they may still be used by QnA. Verify with:

```bash
grep -rn "_get_criteria_context\|CriteriaContextService" app/ --include="*.py"
```

If they are only used by `lessonplan_analysis_service`, leave them in place for this PR (out of scope to remove; see Out of Scope).

**Step 2: Adjust call site in `analyze_lesson_plan`**

The call to `_build_analysis_prompt(...)` should no longer pass `criteria_context`:

```python
full_prompt = self._build_analysis_prompt(
    system_prompt,
    rubric_store_id=rubric_store_id,
    lesson_store_id=user_store_id,
)
```

**Step 3: Run existing analysis tests**

Run: `uv run pytest tests/ -k "analysis or lessonplan" -x`
Expected: PASS (or, if a test asserts on the dropped section, update the test to match the new prompt body.)

**Step 4: Commit**

```bash
git add app/services/lessonplan_analysis_service.py tests/
git commit -m "fix(analysis): drop redundant criteria Vector Search pre-fetch

The main generate_content call already searches rubric_store_id via the
File Search tool; the pre-fetch was duplicating that embedding query
and contributing to 429 RESOURCE_EXHAUSTED quota pressure."
```

---

### Task 3: Wrap the main analyze `generate_content` call with retry

**Files:**
- Modify: `app/services/lessonplan_analysis_service.py`

**Step 1: Apply the retry helper**

The SDK call is sync (`generate_content`), so we wrap it through `asyncio.to_thread` to keep the event loop responsive, and apply the retry decorator there.

```python
# Top of file
from app.utils.gemini_retry import (
    retry_on_resource_exhausted,
    GeminiQuotaExhausted,
)

# Define an inner sync function inside analyze_lesson_plan or as a method:
@retry_on_resource_exhausted(max_attempts=3, initial_wait=2.0, max_wait=16.0)
def _call_gemini_with_file_search(
    client, model, contents, rubric_store_id, user_store_id
):
    return client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            tools=[types.Tool(
                file_search=types.FileSearch(
                    file_search_store_names=[rubric_store_id, user_store_id]
                )
            )],
            temperature=0.7,
        ),
    )

# In analyze_lesson_plan:
response = await asyncio.to_thread(
    _call_gemini_with_file_search,
    self.client, self.model_name, full_prompt,
    rubric_store_id, user_store_id,
)
```

**Step 2: Add explicit `GeminiQuotaExhausted` handler**

In the existing try/except block of `analyze_lesson_plan`, add a handler that returns a structured error so the router can map to HTTP 429:

```python
except GeminiQuotaExhausted as e:
    logger.error(f"Gemini 쿼터 소진 (재시도 후 실패): {e}")
    return {
        "success": False,
        "error": "현재 분석 요청량이 많습니다. 잠시 후 다시 시도해주세요.",
        "error_code": "RESOURCE_EXHAUSTED",
    }
```

**Step 3: Run tests**

Run: `uv run pytest tests/ -k "analysis or lessonplan" -x`
Expected: PASS

**Step 4: Commit**

```bash
git add app/services/lessonplan_analysis_service.py
git commit -m "fix(analysis): retry Gemini 429 with exponential backoff

Wraps the File Search generate_content call in a 429-aware tenacity
retry (3 attempts, 2s/4s/8s). On final failure, raises
GeminiQuotaExhausted so the router can return HTTP 429."
```

---

### Task 4: Map quota exhaustion to HTTP 429 in the router

**Files:**
- Modify: `app/routers/lessonplan_analysis.py`

**Step 1: Branch on `error_code`**

Update the `analyze_lesson_plan` POST handler so a `RESOURCE_EXHAUSTED` result produces HTTP 429 instead of a generic 500:

```python
if not result.get("success"):
    if result.get("error_code") == "RESOURCE_EXHAUSTED":
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=result.get("error", "잠시 후 다시 시도해주세요."),
            headers={"Retry-After": "30"},
        )
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=result.get("error", "분석 중 오류 발생"),
    )
```

**Step 2: Frontend smoke-check**

In the analyze button handler in the frontend (if it currently shows a generic "오류" toast on non-2xx), confirm that an HTTP 429 surfaces the `detail` text. If it does not, file a separate follow-up issue — frontend toast wiring is out of scope here.

**Step 3: Run router tests**

Run: `uv run pytest tests/ -k "router or lessonplan_analysis" -x`
Expected: PASS

**Step 4: Commit**

```bash
git add app/routers/lessonplan_analysis.py
git commit -m "fix(router): return HTTP 429 with Retry-After when quota exhausted"
```

---

### Task 5 (Optional): Stable model for evaluations

**Why:** `gemini-3-flash-preview` is a preview model with tight embedding quotas. A stable Flash release typically has substantially higher embedding throughput.

**Files:**
- Modify: `app/config.py:65-68` (change `GEMINI_EVAL_MODEL` default)
- Modify: `.env` (operator change, document in README if there is one)

**Step 1: Bump default**

Change the default for `GEMINI_EVAL_MODEL` from `"gemini-3-flash-preview"` to a stable model the project has confirmed access to (e.g. `"gemini-2.5-flash"`). Do not also change `GEMINI_QNA_MODEL` in the same commit — QnA quality should be re-checked separately.

**Step 2: Manual verify**

Upload a sample PDF, click 분석하기, confirm the analysis completes and the report looks sensible.

**Step 3: Commit**

```bash
git add app/config.py
git commit -m "chore(config): default GEMINI_EVAL_MODEL to stable Flash release

Preview models carry tighter embedding quotas, which contributed to
429 RESOURCE_EXHAUSTED during lesson plan analysis."
```

---

## Acceptance Criteria

- [ ] Uploading a PDF and clicking 분석하기 succeeds end-to-end on a fresh API quota.
- [ ] When the quota IS exhausted, the server returns **HTTP 429** with a Korean retry message and a `Retry-After` header — not HTTP 500 with "분석 중 오류 발생".
- [ ] Server logs show at most **one** `generate_content` invocation per analyze (the redundant criteria pre-fetch is gone).
- [ ] Transient 429s recover automatically (verified via unit test on the retry helper).
- [ ] `uv run pytest` passes.

## Out of Scope

- Removing `CriteriaContextService` / `_get_criteria_context` entirely — they may still be referenced by the QnA path. Keep them; only stop calling them from `analyze_lesson_plan`.
- Frontend toast / spinner copy changes.
- Application-level concurrency limiter (semaphore around `analyze_lesson_plan`). Worth a follow-up issue if 429s persist after Tasks 1–4 ship.
- Migrating QnA model (`GEMINI_QNA_MODEL`) off preview — separate decision.

## Verification Steps

```bash
# Unit tests
uv run pytest tests/utils/test_gemini_retry.py -x
uv run pytest tests/ -k "analysis or lessonplan or router" -x

# Manual end-to-end
# 1. Start the server
uv run uvicorn app.main:app --reload
# 2. Log in as a normal user
# 3. Upload any small PDF lesson plan
# 4. Click 분석하기 — analysis should complete in ~30–180s
# 5. Inspect server logs: exactly one "generate_content" line per analyze
```
