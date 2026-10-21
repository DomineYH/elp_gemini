# google-genai 구조화 출력·병렬 호출 사실 확인 (#132)

작성일: 2026-10-21. 질문: 학생 반응을 페르소나별 병렬 호출 + JSON 구조화 출력으로 받되 국면당 10초(4명 기준) 안에 끝낼 수 있는가?

이 문서는 사실 정리만 담는다(권고 없음). 1차 소스(저장소 코드, 설치된 SDK 소스, ai.google.dev, googleapis.github.io/python-genai, github.com/googleapis/python-genai, pypi.org)에서 확인되지 않은 항목은 **미확인**으로 표시한다. 온라인 문서는 2026-10-21 조회 기준이며, 인용문은 원문 그대로 옮겼다.

---

## 1. 로컬 사실 (저장소·설치 환경)

### 1.1 설치 버전

| 항목 | 값 | 근거 |
|---|---|---|
| 선언 | `google-genai>=1.60.0` | `pyproject.toml:17` |
| 잠금(lock) | `google_genai-1.60.0` (PyPI 업로드 2026-01-21) | `uv.lock:513`, `uv.lock:528-530` |
| 실제 설치 | `1.60.0` | `/mnt/d/dev/elp_gemini/.venv/lib/python3.12/site-packages/google/genai/version.py` `__version__ = '1.60.0'`; `uv pip show google-genai` |
| SDK 의존성(lock) | httpx 0.28.1, tenacity 9.1.2, pydantic 2.12.4 | `uv.lock:672`, `uv.lock:1442`, `uv.lock:986` |
| PyPI 최신 | 2.32.0 (2026-10-21 업로드), `requires_python >=3.10` | https://pypi.org/project/google-genai/ |

`requirements*.txt`는 없음(uv/pyproject 단일 관리). 설치본은 최신보다 약 9개월 뒤처진 버전이다.

### 1.2 모델 ID 설정

- 기본값은 `gemini-3.1-flash-lite` (QnA·평가 모두): `app/config.py:62-68`, `.env.example:36-37`, `README.md:16`.
- 티켓 본문의 "프로젝트 기본 `gemini-3-flash-preview`"는 **현재 코드와 다르다**. `git log -S` 기준 `gemini-3-flash-preview`는 커밋 `2168e5f`에서 도입, `c42781e`(#88/#89)에서 `gemini-3.1-flash-lite`로 교체됨. `docs/plans/2026-05-13-fix-429-resource-exhausted.md:34`는 교체 전 상태를 서술한다.

### 1.3 클라이언트 생성·호출 방식 — 전부 동기 클라이언트, `client.aio` 사용처 없음

`grep -rn "\.aio\.\|response_mime_type\|response_schema\|\.parsed" app` → 0건. 구조화 출력(JSON 스키마)은 현재 어디에서도 쓰지 않는다.

| 파일 | 클라이언트 | 호출 | config 필드 | 비동기 처리 / 예외→HTTP |
|---|---|---|---|---|
| `app/services/qna_service.py:44-47` | `genai.Client(api_key=..., http_options={'api_version': 'v1beta'})` | `self.client.models.generate_content(...)` `:293-301` | `system_instruction`, `tools=[FileSearch]`, `temperature=settings.QNA_TEMPERATURE` (기본 0.7, `app/config.py:95`) | `async def ask_question` (`:52`) 안에서 **동기 호출을 직접 실행** (`to_thread` 없음) → 호출 중 이벤트 루프 블로킹. 예외는 `:366-368`에서 로그 후 re-raise; 라우터 `app/routers/qna.py:216-232`에서 `ValueError→404`, 그 외 **모두 500**. 429/503 구분 없음, 재시도 없음. |
| `app/services/lessonplan_analysis_service.py:148-151` | `genai.Client(api_key=..., http_options={'api_version': 'v1beta'})` | 1패스 `_retrieve_lessonplan_text` `:72-85` (`temperature=0.2`), 2패스 `_call_gemini_with_file_search` `:122-133` (`temperature=0.7`), 둘 다 `client.models.generate_content` 동기 | `tools=[FileSearch]`, `temperature` | `asyncio.to_thread`로 스레드 오프로드 `:301-305`; 전체 `asyncio.timeout(180)` `:182`. 재시도: `@retry_on_resource_exhausted(max_attempts=3, initial_wait=2.0, max_wait=16.0)` `:89`. 매핑: `GeminiQuotaExhausted`→`error_code="RESOURCE_EXHAUSTED"` `:509-518` → `app/routers/lessonplan_analysis.py:68-73` **429 + `Retry-After: 30`**; `GeminiServerOverloaded`→`MODEL_OVERLOADED` `:520-529` → `:74-82` **503 + `Retry-After: 30`**; `asyncio.TimeoutError` `:505-507` → `success=False` → 500; 기타 → 500 `:83-85`. |
| `app/services/eval_service.py:38-40` | `genai.Client(api_key=...)` (api_version 미지정) | `self.client.models.generate_content` `:171-177` 동기 | `temperature=0.3` | `async def _execute_evaluation` (`:157`) 안에서 동기 직접 호출. 예외 `:188-190` 로그 후 re-raise; 라우터 `app/routers/evaluations.py:87-101` `ValueError→400`, 그 외 500. 재시도 없음. |
| `app/services/file_search_service.py:119`, `:562` | 클래스 공유 `genai.Client` | 동기 | — | 참고. |

### 1.4 기존 재시도 로직 (`app/utils/gemini_retry.py`)

- tenacity 데코레이터 `retry_on_resource_exhausted` (`:58-100`): `ClientError.code == 429` (`:43-46`) 또는 `ServerError.code ∈ {500,502,503,504}` (`:32`, `:49-52`)일 때만 재시도, 지수 백오프(`initial_wait`×2ⁿ, `max_wait` 상한). 소진 시 `GeminiQuotaExhausted` / `GeminiServerOverloaded`로 변환 (`:80-96`).
- **동기 callable 전용** (`Callable[..., T]`를 `tenacity.Retrying`으로 감쌈). `client.aio` 코루틴 함수에 그대로 붙이면 코루틴 객체가 즉시 반환되어 예외가 잡히지 않는다.
- 적용처는 `lessonplan_analysis_service.py:89` 한 곳. QnA·eval 경로에는 재시도 없음.
- 병렬 N건에 각각 적용하면 각 건이 독립적으로 최대 3회 시도, 대기 합계 최대 2+4=6초(3회 시도 사이 2회 대기; `wait_exponential(multiplier=2.0, max=16.0)`)까지 지연될 수 있다.

### 1.5 설치된 SDK 1.60.0 소스에서 확인한 사실 (`.venv/lib/python3.12/site-packages/google/genai/`)

- **SDK 자체 재시도는 기본 꺼져 있음**: `_api_client.py:471-482` `retry_args(options)` — docstring "If None, the 'never retry' stop strategy will be used." / `if options is None: return {'stop': tenacity.stop_after_attempt(1), 'reraise': True}`. 클라이언트는 `retry_args(self._http_options.retry_options)`로 `Retrying`/`AsyncRetrying`을 만들며 (`:742-745`), `models` 경로에서 기본 `HttpRetryOptions()`를 채우는 코드는 없다 (`client.py:137`, `:497`은 `interactions` 경고용). 요청 단위 `retry_options`도 지원 (`:1216-1218`, `:1361-1362`).
- 켜면 기본값: `attempts=5`(원 호출 포함), `initial_delay=1.0s`, `max_delay=60s`, `exp_base=2`, `jitter=1`, 대상 코드 `408,429,500,502,503,504` (`_api_client.py:452-468`; `types.py:1849-1877` `HttpRetryOptions` docstring 동일: "If not specified, default to 5." / "a default set of retryable codes (408, 429, and 5xx) may be used.").
- `types.HttpOptions.timeout`: "Timeout for the request in milliseconds." (`types.py:1925-1926`)
- `GenerateContentConfig` 필드 존재 (`types.py:5038-`): `temperature` `:5059`, `max_output_tokens` `:5088`, `seed` `:5125`, `response_mime_type` `:5132`, `response_schema` `:5143`, `response_json_schema` `:5156`, `thinking_config` `:5238`.
  - `seed` docstring: "When ``seed`` is fixed to a specific number, the model makes a **best effort** to provide the same response for repeated requests. By default, a random number is used." (`:5125-5130`)
  - `response_mime_type` docstring: `text/plain`(기본), `application/json`; "The model needs to be prompted to output the appropriate response type, otherwise the behavior is undefined. This is a preview feature." (`:5132-5142`)
  - `response_schema: Optional[SchemaUnion]`, `SchemaUnion = Union[dict[Any, Any], type, Schema, builtin_types.GenericAlias, VersionedUnionType]` (`:4283-4285`) → pydantic 모델 클래스, `list[Model]`(GenericAlias), dict, `types.Schema` 모두 허용. docstring: "These types can be objects, but also primitives and arrays." / "If `response_schema` doesn't process your schema correctly, try using `response_json_schema` instead." (`:5143-5155`)
  - `response_json_schema`: "If set, `response_schema` must be omitted, but `response_mime_type` is required." 지원 키워드 제한 목록(`$id,$defs,$ref,$anchor,type,format,title,description,enum,items,prefixItems,minItems,maxItems,minimum,…`) (`:5156-`).
- `GenerateContentResponse.parsed: Optional[Union[pydantic.BaseModel, dict, Enum]]` (`types.py:6770-6772`): "First candidate from the parsed response if response_schema is provided. Not available for streaming." 파싱 로직 `:6955-7010`: pydantic 클래스면 `model_validate_json`, `list[Model]` 등 GenericAlias면 Placeholder 모델로 검증; `pydantic.ValidationError`/`JSONDecodeError`는 **조용히 삼켜져 `parsed=None`**이 된다(예외 없음). dict/`types.Schema` 스키마는 `parsed`가 채워지지 않으므로 `response.text`를 직접 `json.loads` 해야 한다.
- 비동기: `client.aio` 프로퍼티 `client.py:560`, `AsyncModels` `models.py:5797`, `AsyncModels.generate_content` `models.py:6963`. HTTP 백엔드는 httpx (`_api_client.py:47`), aiohttp는 설치돼 있으면 선택 사용 (`:68-72`).

---

## 2. 온라인 1차 소스 사실

### 2.1 문서 드리프트 주의

현재 ai.google.dev의 구조화 출력 문서는 새 **Interactions API**(`client.interactions.create` / `response_format`) 기준으로 바뀌었고, `generateContent` 기준 내용은 "(Legacy)" 페이지로 이동했다. REST 레퍼런스는 `responseSchema`·`responseJsonSchema`를 **deprecated**(→ `responseFormat`)로 표시한다. 설치본 1.60.0(2026-01-21)은 Interactions 이전 세대이므로, SDK 동작은 1.60.0 태그 소스로 확인했다.

### 2.2 구조화 출력 (`response_mime_type="application/json"` + 스키마)

| 사실 | 출처 |
|---|---|
| 현재 구조화 출력 페이지는 Interactions API만 다루며 `generate_content`, `response_schema`, `response_json_schema`, `propertyOrdering`을 언급하지 않는다. 예시: `response_format={"type": "text", "mime_type": "application/json", "schema": Recipe.model_json_schema()}` → `Recipe.model_validate_json(interaction.output_text)`. | https://ai.google.dev/gemini-api/docs/structured-output |
| 제한: "Schema subset: Not all JSON Schema features are supported." / "Schema complexity: Very large or deeply nested schemas may be rejected." / "`minProperties` and `maxProperties` are not enforced during constrained decoding and are ignored by the server." 구조화 출력 + 내장 도구 결합: "This feature is available only to Gemini 3 series models." | 같은 페이지 |
| Legacy(generateContent) 페이지: "To generate a JSON object, set `response_json_schema` (or `responseFormat.text.schema` in REST) in the generation configuration." 예시 `"response_json_schema": Recipe.model_json_schema()`, 파싱은 `Recipe.model_validate_json(response.text)`. `response.parsed`·`response_schema`는 언급 없음. 순서: "the model will produce outputs in the same order as the keys in the schema." / "Gemini 2.0 requires an explicit `propertyOrdering` list". 제한: "The model ignores unsupported properties." / "The API may reject very large or deeply nested schemas." / "try simplifying your schema by shortening property names, reducing nesting, or limiting the number of constraints." 지원 모델 목록에 3.1 Flash-Lite, 2.5 Flash-Lite 등 포함. 최상위 배열 스키마는 다루지 않음(배열은 중첩 필드 예시만). | https://ai.google.dev/gemini-api/docs/generate-content/structured-output |
| REST `GenerationConfig`: `responseSchema` "(deprecated) … Schemas must be a subset of the OpenAPI schema and can be objects, primitives or arrays. If set, a compatible responseMimeType must also be set. … Deprecated. Use responseFormat instead." `responseJsonSchema` "(deprecated) … If set, responseSchema must be omitted, but responseMimeType is required. … only the following properties are supported: $id $defs $ref $anchor type format title description enum (for strings and numbers) items prefixItems minItems maxItems minimum maximum anyOf oneOf (interpreted the same as anyOf) properties additionalProperties required. The non-standard propertyOrdering property may also be set. Cyclic references are unrolled to a limited degree…" | https://ai.google.dev/api/generate-content |
| python-genai README/문서: "Schemas can be provided as standard JSON schema." / "Schemas can be provided as Pydantic Models." 예시 `config={'response_mime_type': 'application/json', 'response_json_schema': user_profile}` → `print(response.parsed)`; pydantic 예시는 `response_schema=CountryInfo` + `response_mime_type='application/json'`. 주의: "don't duplicate it in your input prompt, including by giving examples of expected JSON output." / "If you do, the generated output might be lower in quality." | https://googleapis.github.io/python-genai/ , https://github.com/googleapis/python-genai/blob/main/README.md |
| 1.60.0 태그 소스: §1.5와 동일 (`SchemaUnion`, `parsed` "Not available for streaming.", `Schema.property_ordering` "Not a standard field in open api spec. Only used to support the order of the properties."). | https://raw.githubusercontent.com/googleapis/python-genai/v1.60.0/google/genai/types.py |
| CHANGELOG(1.60.0 이후) 스키마 관련: 1.74.0 "Add one_of support to JSONSchema for Agent Platform"; 2.17.0 "Add propertyOrdering auto-population for ResponseSchema and ResponseJsonSchema for Dotnet SDK"; 2.18.0 "Enable json schema in FunctionDeclaration parser". `response_schema`/`parsed` 제거 항목 없음. 최신 "[2.32.0] … (2026-10-21)". | https://github.com/googleapis/python-genai/blob/main/CHANGELOG.md |

### 2.3 비동기 클라이언트·HTTP 스택·재시도

| 사실 | 출처 |
|---|---|
| "`client.aio` exposes all the analogous async methods that are available on `client`." / "By default we use httpx for both sync and async client implementations." / "In order to have faster performance, you may install `google-genai[aiohttp]`." | https://googleapis.github.io/python-genai/ |
| 동시 호출 수(세마포어, 병렬 권장치)는 README/문서에 **언급 없음 → 미확인**. | 같은 페이지 |
| `HttpOptions.timeout` "Timeout for the request in milliseconds."; `retry_options` "HTTP retry options for the request."; `HttpRetryOptions.attempts` "If 0 or 1, it means no retries. If not specified, default to 5." 등 (§1.5와 동일). | https://raw.githubusercontent.com/googleapis/python-genai/v1.60.0/google/genai/types.py |
| 1.60.0 코드에서 재시도는 **opt-in** (§1.5). 반면 Troubleshooting 문서는 SDK가 "include automatic retry logic with exponential backoff by default" / "the Python SDK automatically retries transient errors up to four times with an initial delay of approximately 1 second"(최대 60초, "rate limits (`429` and `5xx` status codes)")라고 서술하며 `HttpRetryOptions`를 언급하지 않는다. **문서와 1.60.0 코드가 불일치** — "기본 켜짐"은 1.60.0 기준 미확인(코드상 꺼짐). | https://ai.google.dev/gemini-api/docs/troubleshooting ; https://raw.githubusercontent.com/googleapis/python-genai/v1.60.0/google/genai/_api_client.py |
| CHANGELOG 재시도 이력: 1.21.0(2025-06-18) "Add retries to http client"; 1.24.0 "Retry on exception instead of a status code"; 1.28.0 "Support retry configuration at request level", "Retry async when seeing aiohttp ClientConnectorError, ClientOSError, ServerDisconnectedError"; 1.47.0(2025-10-29) "Support retries in API requests" / "Add documentation for the retry behavior". 1.60.0 이후: 1.67.0 "Forward http_options in async_request_streamed to enable retry support"; 1.68.0 "Treat `attempts=0` as `attempts=1` in retry options to ensure no retries"; 1.74.0(2026-04-29) "retry: Retry on httpx.TimeoutException with HttpRetryOptions"; 1.65.0 "Make aiohttp an optional dependency"; 2.30.0 "Raise default HTTP timeouts so long-running requests aren't killed client-side". | https://github.com/googleapis/python-genai/blob/main/CHANGELOG.md |

### 2.4 속도 제한(RPM)·오류 코드

| 사실 | 출처 |
|---|---|
| "Rate limits are usually measured across three dimensions:" RPM, "Tokens per minute (input) (TPM)", RPD. "Rate limits are applied per project, not per API key." / "Limits vary depending on the specific model being used" / "exceeding any of them will trigger a rate limit error." / "if your RPM limit is 20, making 21 requests within a minute will result in an error" / "Specified rate limits are not guaranteed and actual capacity may vary." | https://ai.google.dev/gemini-api/docs/rate-limits |
| **모델별 RPM/TPM/RPD 숫자표: 미확인.** 현재 페이지에는 generateContent용 모델별 표가 없고 "Rate limits depend on a variety of factors (such as your usage tier) and can be viewed in Google AI Studio."라고만 적혀 있다. 티어 정의: Free "Active project or free trial"; Tier 1 "Set up and link an active billing account"; Tier 2 "Paid $100 + 3 days from first successful payment"; Tier 3 "Paid $1,000 + 30 days". 10분 단위 지출 상한: Free N/A, Tier 1 $10, Tier 2 $50, Tier 3 $200; "If you hit a spend-based rate limit, the API returns a `429 RESOURCE_EXHAUSTED` error." Batch enqueued-tokens 표만 모델별 존재(Gemini 3.1 Flash Lite: Tier 1 10,000,000 / Tier 2 500,000,000 / Tier 3 1,000,000,000; Gemini 3 Flash Preview 없음). | 같은 페이지 |
| 이 프로젝트 API 키의 **현재 티어: 미확인**(AI Studio에서만 확인 가능, 저장소에 기록 없음). | — |
| Troubleshooting: "Only retry on transient errors (like `429`, `408`, or `5xx`)." / "Add random "jitter" to the delay" / "Define a maximum number of retry attempts". | https://ai.google.dev/gemini-api/docs/troubleshooting |
| API errors: 429 `rate_limit_exceeded` "You have exceeded the per-minute or per-second request or token limit." → "Wait and retry with exponential backoff."; 429 `quota_exceeded` "You have exceeded your daily quota."; 503 `service_unavailable` "The service is temporarily overloaded or down." → "Wait and retry with exponential backoff."; 500 `api_error` → "Retry the request."; 504 `deadline_exceeded` → "Remove or increase client deadline setting to use the server default." | https://ai.google.dev/gemini-api/docs/api-errors |

### 2.5 모델 ID·한도·가격

| 사실 | 출처 |
|---|---|
| **`gemini-3.1-flash-lite`는 실제 현행(stable) 모델 ID다.** 모델 페이지(Last updated 2026-10-19)의 gemini-3/flash-lite 계열: stable `gemini-3.8-flash`, `gemini-3.6-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, `gemini-3.1-flash-image`, `gemini-3.1-flash-lite-image`, `gemini-3-pro-image`, `gemini-3.8-flash-tts`, `gemini-3.8-flash-lite-tts`; preview `gemini-3.1-pro-preview`, `gemini-3-flash-preview`, `gemini-3.1-flash-live-preview`, `gemini-3.1-flash-tts-preview`; shut down `gemini-3.1-flash-lite-preview`, `gemini-3-pro-preview`; 구세대 `gemini-2.5-flash-lite`, `gemini-2.0-flash-lite`. `gemini-3-flash-lite*` ID는 존재하지 않음. | https://ai.google.dev/gemini-api/docs/models |
| `gemini-3-flash-preview`: 입력 "1,048,576", 출력 "65,536", latest update "December 2025", structured outputs/caching/thinking "Supported"; 버전표에 "Preview: gemini-3-flash-preview"만; 폐기/종료 공지 없음; **지연 시간 수치 없음**. | https://ai.google.dev/gemini-api/docs/models/gemini-3-flash-preview |
| `gemini-3.1-flash-lite`: 입력 "1,048,576", 출력 "65,536", latest update "May 2026", structured outputs/caching/thinking "Supported"; "low-latency, cost-effective multimodal model optimized for high-frequency, lightweight tasks". **지연 시간 수치 없음.** | https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite |
| `gemini-3.5-flash-lite`: 입력 "1,048,576", 출력 "65,536", latest update "July 2026"; "a low-latency, cost-effective multimodal model". | https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite |
| "Gemini 3 models have a knowledge cutoff of January 2025." / "Gemini 3 models support a 1 million token input context window and up to 64k tokens of output." | https://ai.google.dev/gemini-api/docs/gemini-3 |
| 가격(Standard, 1M 토큰당): `gemini-3-flash-preview` 무료 티어 "Free of charge"; 입력 "$0.50 (text / image / video)" / "$1.00 (audio)"; 출력 "$3.00"; 캐시 "$0.05". `gemini-3.1-flash-lite` "Free of charge"; 입력 "$0.25" / "$0.50 (audio)"; 출력 "$1.50"; 캐시 "$0.025". `gemini-3.5-flash-lite` 입력 "$0.30"; 출력 "$2.50"; 캐시 "$0.03". `gemini-2.5-flash-lite` 입력 "$0.10" / "$0.30 (audio)"; 출력 "$0.40"; 캐시 "$0.01". `gemini-3.8-flash`/`gemini-3.6-flash` 입력 "$0.75 through December 31, 2026." / "$1.50 starting January 1, 2027."; 출력 "$3.75" / "$7.50". `gemini-3.1-pro-preview` 무료 티어 "Not available". | https://ai.google.dev/gemini-api/docs/pricing |

요약: `gemini-3.1-flash-lite`는 `gemini-3-flash-preview` 대비 입력 1/2, 출력 1/2 가격이며 토큰 한도는 동일. 두 모델 간 **지연 시간 비교 수치는 문서에 없음(미확인)**.

### 2.6 `temperature`·`seed`

| 사실 | 출처 |
|---|---|
| 1.60.0 `GenerateContentConfig.temperature`: "Value that controls the degree of randomness in token selection." `seed`: "the model makes a best effort to provide the same response for repeated requests." (`candidate_count`, `max_output_tokens`도 존재) | https://raw.githubusercontent.com/googleapis/python-genai/v1.60.0/google/genai/types.py |
| REST: `seed` "Optional. Seed used in decoding. If not set, the request uses a randomly generated seed." (**결정성 보장 문구 없음**). `temperature` "Controls the randomness of the output. … Values can range from [0.0, 2.0]. This field is no longer supported and is silently ignored on Gemini 3.6 Flash and newer models." `candidateCount` "If unset, this will default to 1." `thinkingLevel` "Recommended for Gemini 3 or later models." | https://ai.google.dev/api/generate-content |
| Gemini 3 가이드: "we strongly recommend keeping the temperature parameter at its default value of 1.0." / "Changing the temperature (setting it below 1.0) may lead to unexpected behavior, such as looping or degraded performance". `thinking_level` 미지정 시 "Gemini 3 will default to `high`." / "You cannot use both `thinking_level` and the legacy `thinking_budget` parameter in the same request." | https://ai.google.dev/gemini-api/docs/gemini-3 |

참고(로컬): 현재 코드는 Gemini 3 계열 모델에 `temperature=0.2/0.3/0.7`을 지정하고 있다 (§1.3). `seed`는 어디에서도 지정하지 않는다.

---

## 3. "N건 병렬 페르소나 호출" vs "1건 호출로 N개 JSON 배열" — 문서화된 사실만 비교

| 축 | N건 병렬 (예: 4~6 × `client.aio.models.generate_content`) | 1건 (N항목 배열 스키마) | 근거 |
|---|---|---|---|
| RPM 소비 | 국면당 N 요청 | 국면당 1 요청 | rate-limits: RPM·TPM·RPD 중 "exceeding any of them will trigger a rate limit error."; RPM 수치 자체는 미확인(AI Studio 전용) |
| TPM(입력) 소비 | 공통 프롬프트(시스템·맥락)가 N번 전송됨 | 1번 | rate-limits "Tokens per minute (input) (TPM)" |
| 출력 상한 | 호출당 65,536 토큰 × N | 65,536 토큰에 N명분이 함께 들어가야 함 | 모델 페이지 출력 "65,536"; gemini-3 "up to 64k tokens of output" |
| 429 노출 | 요청 N건 각각이 429/503 대상; 기존 `retry_on_resource_exhausted`는 동기 전용이라 `aio` 경로에 재사용 불가(§1.4); SDK 자체 재시도는 1.60.0에서 opt-in(§1.5) | 1건만 대상 | §1.4, §1.5, api-errors |
| 캐싱 | 암시적 캐싱은 "enabled by default for all Gemini 2.5 and newer models"; 최소 토큰표에 `gemini-3-flash-preview`·`3.1-flash-lite`·`2.5-flash-lite`는 없음(미확인); 권장 "Try putting large and common contents at the beginning of your prompt" / "Try to send requests with similar prefix in a short amount of time"; 할인율 수치 없음 | 해당 없음(단일 요청) | https://ai.google.dev/gemini-api/docs/caching |
| 스키마 | 페르소나별 단일 객체 스키마 | 배열/중첩 스키마 — "Very large or deeply nested schemas may be rejected."; 최상위 배열 제한에 대한 문구 없음(미확인); 키 순서는 스키마 키 순서를 따름 | structured-output (current/legacy) |
| 지연 시간 | 문서에 모델별 지연 수치 없음 → **미확인**. 병렬 N건의 벽시계 시간은 가장 느린 1건에 의해 결정된다는 점은 asyncio 일반 동작이며 Gemini 문서 사항이 아님 | 단일 호출의 출력 토큰 수가 N배 → 생성 시간 관계는 문서에 수치 없음 → **미확인** | — |
| 재현성 | 호출마다 `seed` 지정 가능(best effort) | 1개 `seed` | §2.6 |
| `candidate_count` | — | 같은 프롬프트에 대한 N개 샘플일 뿐 페르소나별 분기 수단이 아님 ("Number of response variations to return.") | https://ai.google.dev/api/generate-content |
| 품질 비교 | 1차 소스에 "다중 페르소나 단일 호출 vs 분리 호출" 품질 비교 **없음 → 미확인**. 구조화 출력 문서의 품질 관련 문구는 "don't duplicate [schema] in your input prompt … the generated output might be lower in quality." 뿐 | | README |

국면당 10초(4명) 달성 가능 여부는 위 표의 지연 항목이 모두 미확인이므로 **문서만으로는 판단 불가**; 실측이 필요하다(이 문서 범위 밖).

---

## 4. 미확인 항목 목록

1. 모델별 RPM/TPM/RPD 수치(현재 문서에 표 없음, AI Studio에서만 확인).
2. 이 프로젝트 API 키의 사용 티어.
3. `gemini-3-flash-preview` vs `gemini-3.1-flash-lite` 지연 시간 수치.
4. 암시적 캐싱 최소 토큰(두 모델 모두 표에 없음)·할인율.
5. 최상위 배열 `response_schema`의 공식 지원/제한 문구.
6. Troubleshooting 문서의 "SDK 기본 재시도 켜짐" 주장이 1.60.0에 적용되는지(코드상은 꺼짐).
7. python-genai 문서의 권장 동시 호출 수.
8. 페르소나 병렬 vs 단일 배열 응답의 품질 비교(1차 소스 없음).
