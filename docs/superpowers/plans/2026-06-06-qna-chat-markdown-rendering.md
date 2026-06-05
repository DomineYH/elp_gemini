# QnA 실시간 챗봇 마크다운 렌더링 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 라이브 QnA 챗봇의 AI 답변을 기존 `renderSafeMarkdown()` 파이프라인으로 렌더링하여, 마크다운(`**굵게**`/헤더/목록/코드)이 raw 기호가 아니라 서식으로 표시되도록 한다.

**Architecture:** `app/templates/user/dashboard.html` 단일 파일의 실시간 대화 렌더 함수 두 개(`addMessage`, `updateMessage`)에서 `type === 'ai'`일 때만 `div.textContent = text`를 `div.innerHTML = prose 래핑 + renderSafeMarkdown(text)`로 교체한다. `renderSafeMarkdown`·`sanitizeRenderedMarkdown`·`marked`는 같은 파일에 이미 존재하며 히스토리(L1118)에서 검증된 패턴을 그대로 재사용한다. 서버·백엔드·의존성 변경 없음.

**Tech Stack:** FastAPI + Jinja2Templates (`app/templates`), Tailwind CSS (CDN, base.html), `marked` (CDN, dashboard.html L523). venv: `.venv`.

**Spec:** `docs/superpowers/specs/2026-06-06-qna-chat-markdown-rendering-design.md` · **Issue:** #110

**테스트 전략 노트:** 본 변경은 Jinja 템플릿 내 인라인 JS이며 프로젝트에 JS 단위 테스트 하니스가 없다(파이썬/pytest 전용). JS 테스트 프레임워크 신규 도입은 YAGNI·외과적 변경 원칙에 위배되므로, 검증은 (a) 정적 grep 어서션과 (b) 런타임 Playwright 행동/시각 검증(프로젝트의 기존 UI 검증 방식)으로 수행한다.

**검증 중 발견된 추가 변경(Task 0):** base.html이 Tailwind를 typography 플러그인 없이 로드해 `prose`가 무효화된다. Playwright 하니스 비교 결과, 이를 활성화하지 않으면 목록 불릿·헤더 강조가 사라져 "가독성" 목표를 달성하지 못한다. 따라서 base.html에 `?plugins=typography`를 추가한다(사용자 승인 완료).

---

### Task 0: `base.html` — Tailwind typography 플러그인 활성화

**Files:**
- Modify: `app/templates/base.html` (L14, Tailwind CDN script)

- [ ] **Step 1: 현재 라인 확인**

Run: `grep -n "cdn.tailwindcss.com" app/templates/base.html`
Expected: 1개 매칭 (L14, `?plugins=` 없음)

- [ ] **Step 2: typography 플러그인 활성화**

old_string:
```html
    <script src="https://cdn.tailwindcss.com"></script>
```
new_string:
```html
    <script src="https://cdn.tailwindcss.com?plugins=typography"></script>
```

- [ ] **Step 3: 검증 (정적)**

Run: `grep -n "plugins=typography" app/templates/base.html`
Expected: 1개 매칭 (L14).

---

### Task 1: `addMessage` — AI 메시지를 마크다운으로 렌더링

**Files:**
- Modify: `app/templates/user/dashboard.html` (`addMessage` 함수, 약 L703–726)

- [ ] **Step 1: 현재 함수 위치/형태 확인**

Run: `grep -n "function addMessage" app/templates/user/dashboard.html`
Expected: 1개 매칭 (약 L703)

- [ ] **Step 2: 함수 본문 교체**

아래 `old_string` 전체를 `new_string`으로 교체한다. 변경점은 ① `ai` 클래스 문자열에서 `whitespace-pre-wrap` 제거, ② 본문 주입을 `type === 'ai'` 분기로 변경(나머지 타입은 `textContent` 유지).

old_string:
```javascript
        let classes = "p-3 rounded-lg max-w-[80%] text-sm ";
        if (type === 'user') {
            classes += "bg-blue-100 text-blue-800 ml-auto text-right";
        } else if (type === 'ai') {
            classes += "bg-white border border-gray-200 text-gray-800 mr-auto whitespace-pre-wrap";
        } else if (type === 'system') {
            classes += "bg-gray-100 text-gray-500 text-center text-xs mx-auto";
        } else { // error
            classes += "bg-red-100 text-red-800 text-center text-sm mx-auto";
        }

        div.className = classes;
        div.textContent = text;
        history.appendChild(div);
```

new_string:
```javascript
        let classes = "p-3 rounded-lg max-w-[80%] text-sm ";
        if (type === 'user') {
            classes += "bg-blue-100 text-blue-800 ml-auto text-right";
        } else if (type === 'ai') {
            classes += "bg-white border border-gray-200 text-gray-800 mr-auto";
        } else if (type === 'system') {
            classes += "bg-gray-100 text-gray-500 text-center text-xs mx-auto";
        } else { // error
            classes += "bg-red-100 text-red-800 text-center text-sm mx-auto";
        }

        div.className = classes;
        if (type === 'ai') {
            div.innerHTML =
                '<div class="prose prose-sm max-w-none">'
                + renderSafeMarkdown(text)
                + '</div>';
        } else {
            div.textContent = text;
        }
        history.appendChild(div);
```

- [ ] **Step 3: 교체 검증 (정적)**

Run: `grep -n "renderSafeMarkdown" app/templates/user/dashboard.html`
Expected: 기존 히스토리 사용처(L818 정의, L1118 사용)에 더해 `addMessage` 내부에 신규 1건 추가되어 매칭 수가 늘어난다.

Run: `sed -n '703,730p' app/templates/user/dashboard.html`
Expected: `if (type === 'ai')` 분기에서 `div.innerHTML`로 `prose prose-sm max-w-none` 래핑 + `renderSafeMarkdown(text)` 호출, `else`에서 `div.textContent = text`.

---

### Task 2: `updateMessage` — AI 메시지를 마크다운으로 렌더링 (실제 답변 출력 지점)

**Files:**
- Modify: `app/templates/user/dashboard.html` (`updateMessage` 함수, 약 L728–743)

> 실제 AI 답변은 L688 `updateMessage(loadingId, data.answer, 'ai')`로 출력되므로 이 함수가 사용자 체감의 핵심 지점이다.

- [ ] **Step 1: 현재 함수 위치/형태 확인**

Run: `grep -n "function updateMessage" app/templates/user/dashboard.html`
Expected: 1개 매칭 (약 L728)

- [ ] **Step 2: 함수 본문 교체**

old_string:
```javascript
            let classes = "p-3 rounded-lg max-w-[80%] text-sm ";
            if (type === 'ai') {
                classes += "bg-white border border-gray-200 text-gray-800 mr-auto whitespace-pre-wrap";
            } else if (type === 'error') {
                classes += "bg-red-100 text-red-800 text-center text-sm mx-auto";
            }
            div.className = classes;
            div.textContent = text;
```

new_string:
```javascript
            let classes = "p-3 rounded-lg max-w-[80%] text-sm ";
            if (type === 'ai') {
                classes += "bg-white border border-gray-200 text-gray-800 mr-auto";
            } else if (type === 'error') {
                classes += "bg-red-100 text-red-800 text-center text-sm mx-auto";
            }
            div.className = classes;
            if (type === 'ai') {
                div.innerHTML =
                    '<div class="prose prose-sm max-w-none">'
                    + renderSafeMarkdown(text)
                    + '</div>';
            } else {
                div.textContent = text;
            }
```

- [ ] **Step 3: 교체 검증 (정적)**

Run: `sed -n '728,752p' app/templates/user/dashboard.html`
Expected: `ai` 클래스에 `whitespace-pre-wrap` 없음, `if (type === 'ai')`에서 `div.innerHTML`로 prose 래핑 + `renderSafeMarkdown(text)`, `else`에서 `div.textContent = text`.

Run: `grep -c "whitespace-pre-wrap" app/templates/user/dashboard.html`
Expected: 실시간 대화 함수 2곳에서 제거되어, 변경 전 대비 카운트가 2 감소.

---

### Task 3: 런타임 행동 검증 + 커밋

**Files:**
- 검증 대상: `app/templates/user/dashboard.html` (변경 없음, 동작 확인만)

> 런타임 검증은 실제 Gemini 호출 없이 챗봇 렌더 함수를 직접 호출하여 DOM 결과를 확인한다.

- [ ] **Step 1: 서버 기동**

Run: `.venv/bin/python -m uvicorn app.main:app --port 8011` (백그라운드)
Expected: 기동 성공, 8011 포트 listen.

- [ ] **Step 2: 로그인 후 챗봇이 있는 대시보드 진입 (Playwright)**

테스트 계정으로 로그인하고, 지도안이 업로드되어 `document`가 존재하는 대시보드(`/dashboard`)로 이동한다. `#chatHistory` 요소가 DOM에 존재하는지 확인한다.
Expected: `#chatHistory` 존재.

- [ ] **Step 3: 마크다운 렌더링 검증 (browser_evaluate)**

페이지 컨텍스트에서 다음을 실행:
```javascript
() => {
  const id = addMessage('placeholder', 'system');
  updateMessage(id, '# 제목\n\n**굵게** 그리고 목록:\n- 항목1\n- 항목2\n\n`code`', 'ai');
  const el = document.getElementById(id);
  return {
    hasStrong: !!el.querySelector('strong'),
    hasList: !!el.querySelector('ul li'),
    hasHeading: !!el.querySelector('h1'),
    hasProse: !!el.querySelector('.prose'),
    rawStarsGone: !el.textContent.includes('**'),
  };
}
```
Expected: `hasStrong=true, hasList=true, hasHeading=true, hasProse=true, rawStarsGone=true`.

- [ ] **Step 4: XSS sanitize 검증 (browser_evaluate)**

```javascript
() => {
  const id = addMessage('p', 'system');
  updateMessage(id, '<img src=x onerror=alert(1)> <a href="javascript:alert(1)">x</a> <b>ok</b>', 'ai');
  const el = document.getElementById(id);
  const a = el.querySelector('a');
  return {
    noOnerror: !el.innerHTML.includes('onerror'),
    hrefNeutralized: !a || !(a.getAttribute('href') || '').startsWith('javascript:'),
  };
}
```
Expected: `noOnerror=true, hrefNeutralized=true`.

- [ ] **Step 5: 사용자 말풍선 회귀 확인 (browser_evaluate)**

```javascript
() => {
  const id = addMessage('**not bold**', 'user');
  const el = document.getElementById(id);
  return { userPlain: el.textContent.includes('**not bold**') && !el.querySelector('strong') };
}
```
Expected: `userPlain=true` (사용자 입력은 평문 유지).

- [ ] **Step 6: 서버 종료 후 커밋**

```bash
git add app/templates/user/dashboard.html
git commit -m "feat(ui): QnA 실시간 챗봇 답변 마크다운 렌더링 (#110)

addMessage/updateMessage의 ai 메시지를 기존 renderSafeMarkdown
파이프라인(escape→marked→sanitize)으로 렌더링하고 prose로 래핑.
whitespace-pre-wrap 제거로 prose 블록 간 이중 개행 방지.
히스토리(L1118)와 동일 패턴 재사용, 신규 의존성 없음.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```
Expected: 커밋 성공.

---

## Self-Review

- **Spec coverage:** 목표 3개(① ai 마크다운 렌더, ② 히스토리와 동일 prose 패턴, ③ 의존성 0) → Task 1·2가 ①②③ 모두 구현. 성공 기준 5개 → Task 3 Step 3(서식)·Step 5(사용자 회귀/히스토리 패턴)·Step 4(sanitize)·전 범위(dead 템플릿 미변경)·의존성 0(코드상 import/CDN 추가 없음)로 커버.
- **Placeholder scan:** "TBD/TODO/적절히 처리" 없음. 모든 코드 단계에 실제 old/new 문자열·실행 코드 포함.
- **Type consistency:** 두 함수 모두 동일한 `'<div class="prose prose-sm max-w-none">' + renderSafeMarkdown(text) + '</div>'` 문자열과 `type === 'ai'` 분기명을 사용(불일치 없음). `renderSafeMarkdown`는 L816 기존 정의와 동일 시그니처.
