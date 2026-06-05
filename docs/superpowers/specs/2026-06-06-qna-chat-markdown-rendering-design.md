# QnA 실시간 챗봇 마크다운 렌더링

- 작성일: 2026-06-06
- 작성자: DomineYH (with Claude)
- 상태: 설계 승인됨, 구현 대기

## 배경

`app/templates/user/dashboard.html`의 라이브 QnA 챗봇은 AI 답변을
`marked`(L523에서 CDN 로드)로 받은 마크다운 문자열 그대로 화면에 출력한다.
실시간 대화 렌더링 함수 `addMessage`(L703)·`updateMessage`(L728)가
`div.textContent = text`를 사용하기 때문에, `**굵게**`, `#`, `-`, `1.` 같은
마크다운 기호가 서식으로 변환되지 않고 원문 그대로 노출되어 가독성이 떨어진다.

반면 같은 파일의 **대화 히스토리** 렌더링은 이미 안전한 마크다운 파이프라인을
사용한다.

- `renderSafeMarkdown(markdown)` (L816): `escapeHtml` → `marked.parse()` →
  `sanitizeRenderedMarkdown()`
- `sanitizeRenderedMarkdown(html)` (L781): `on*` 이벤트 핸들러·`style` 속성
  제거, `a[href]`/`img[src]` URL 화이트리스트(`http/https/mailto/tel`) 검증
- 히스토리 적용 지점 (L1118):
  `` `<div class="prose prose-sm max-w-none">${renderSafeMarkdown(message.content)}</div>` ``

즉, 필요한 인프라(라이브러리·렌더 함수·sanitize·스타일 패턴)는 모두 존재하며
**실시간 대화 경로에만 누락**되어 있다.

## 목표

- 라이브 QnA 챗봇의 **AI 답변**을 기존 `renderSafeMarkdown()` 파이프라인으로
  렌더링하여 마크다운이 서식으로 표시되도록 한다.
- 히스토리 렌더링과 동일한 패턴(`<div class="prose prose-sm max-w-none">` 래핑)을
  사용해 일관성을 유지한다.
- 신규 의존성을 추가하지 않는다 (marked 이미 로드, sanitize 이미 존재).

## 비목표 (Out of Scope)

- `viewer.html` / `doc_detail.html`: 동일한 `textContent` raw 출력 문제가 있으나
  현재 어떤 라우터에서도 렌더링되지 않는 **죽은(dead) 템플릿**이므로 본 변경에서
  수정하지 않는다. (CLAUDE.md "외과적 변경" 원칙)
- 사용자 입력 말풍선(`user`), 시스템/에러 말풍선(`system`/`error`)의 렌더링
  방식 변경. 이들은 평문이며 `textContent` 그대로 유지한다(안전·의도된 동작).
- 백엔드 `qna_service` 응답 포맷 변경. 답변은 계속 마크다운 문자열로 반환한다.
- `marked` / sanitize 로직 자체의 개선·교체.

## 상세 설계

대상 파일: **`app/templates/base.html`** (Tailwind typography 활성화) +
**`app/templates/user/dashboard.html`** (실시간 대화 렌더링)

> **검증 중 발견(2026-06-06):** base.html이 Tailwind Play CDN을 typography
> 플러그인 없이 로드하여 `prose` 클래스가 무효화되고, Preflight 리셋이 목록
> 불릿·헤더 크기를 제거한다. 따라서 dashboard.html만 고치면 마크다운이 HTML로
> 파싱은 되지만 목록 기호가 사라지고 헤더가 본문과 동일하게 보여 "가독성" 목표를
> 달성하지 못한다(Playwright 하니스로 before/after 비교 확인). `?plugins=typography`
> 활성화 시 헤더/불릿/번호/blockquote가 정상 렌더링된다. 기존 history(L1118)·분석
> 보고서(L435)의 `prose` 사용처도 함께 정상화된다(잠재 버그 수정).

### 0. `app/templates/base.html` — Tailwind typography 활성화

```html
<!-- 변경 전 -->
<script src="https://cdn.tailwindcss.com"></script>
<!-- 변경 후 -->
<script src="https://cdn.tailwindcss.com?plugins=typography"></script>
```

동일 CDN의 내장 플러그인 활성화이므로 **신규 의존성이 아니다**. typography CSS는
`.prose` 컨테이너에만 적용되므로 비-prose 요소에는 영향이 없다.

### 1. `addMessage(text, type)` (약 L703–726)

`type === 'ai'`인 경우에만 마크다운 렌더링을 적용한다. 그 외 타입은 기존
`textContent` 경로를 유지한다.

- `ai` 버블 클래스 문자열에서 `whitespace-pre-wrap` 제거
  (prose의 블록 요소가 줄간격을 처리하므로 pre-wrap이 남으면 마크다운 원문의
  개행 때문에 빈 줄이 이중으로 생긴다).
- 본문 주입을 분기:
  - `ai`: `div.innerHTML = '<div class="prose prose-sm max-w-none">' + renderSafeMarkdown(text) + '</div>';`
  - 그 외: `div.textContent = text;` (기존 유지)

### 2. `updateMessage(id, text, type)` (약 L728–743)

실제 AI 답변은 L688 `updateMessage(loadingId, data.answer, 'ai')`로 출력되므로
이 함수가 핵심 변경 지점이다. `addMessage`와 동일 규칙 적용.

- `ai` 클래스 문자열에서 `whitespace-pre-wrap` 제거.
- `ai`: `div.innerHTML = '<div class="prose prose-sm max-w-none">' + renderSafeMarkdown(text) + '</div>';`
- `error`: 기존 `textContent` 유지.

### 데이터 흐름

```
질문 제출(L649) → addMessage(question,'user')  [textContent, 변경 없음]
              → addMessage('답변 생성 중...','system')  [textContent, 변경 없음]
POST /api/qna/{docId} 응답 → updateMessage(loadingId, data.answer,'ai')
                            → renderSafeMarkdown(answer) → prose 래핑 → innerHTML
```

### 보안 (XSS)

신규 공격 표면 없음. `renderSafeMarkdown`이 입력 escape → 파싱 →
`on*`/`style`/위험 URL 제거를 이미 수행한다. 히스토리 경로에서 이미 동일하게
신뢰되는 파이프라인을 재사용한다.

## 성공 기준 (검증)

1. 실시간 챗봇 AI 답변에서 헤더(크기·굵기)·굵게·목록(불릿/번호+들여쓰기)·코드·
   blockquote가 **서식 적용**되어 출력된다.
2. 사용자 말풍선은 평문 그대로 유지(회귀 없음), 대화 히스토리도 정상 동작.
3. `<script>`·이벤트 핸들러·`javascript:` URL 등이 포함된 답변에서도
   스크립트가 실행되지 않는다(sanitize 동작 확인).
4. 죽은 템플릿(viewer/doc_detail)은 변경되지 않는다.
5. 신규 의존성·CDN 추가 없음.
