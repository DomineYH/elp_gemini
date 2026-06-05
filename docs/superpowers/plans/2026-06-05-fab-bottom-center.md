# FAB 하단 중앙 이동 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 지도안 업로드 후 나타나는 `분석 시작`/`QnA 챗봇` FAB를 화면 우측 하단에서 하단 중앙(가로 배치)으로 이동한다. dashboard.html, viewer.html 두 곳 모두.

**Architecture:** 순수 Tailwind 유틸리티 클래스 변경. FAB 컨테이너의 위치(`right-8`→`left-1/2 -translate-x-1/2`)와 방향(`flex-col`→`flex-row`, `space-y-4`→`space-x-4`)을 바꾸고, dashboard는 버튼 순서를 `[분석][QnA]`로 재배치하며 호버 툴팁을 버튼 위로 옮긴다. JS·서버 로직 변경 없음.

**Tech Stack:** FastAPI + Jinja2Templates (`app/templates`), Tailwind CSS (CDN, base.html). venv: `.venv`.

**Spec:** `docs/superpowers/specs/2026-06-05-fab-bottom-center-design.md` · **Issue:** #101

---

### Task 1: dashboard.html FAB → 하단 중앙 가로 배치 + 버튼 순서/툴팁 정리

**Files:**
- Modify: `app/templates/user/dashboard.html` (FAB 컨테이너 블록, 약 :352-381)

- [ ] **Step 1: 현재 FAB 블록을 정확히 확인**

Run: `grep -n 'fixed bottom-8 right-8 z-40 flex flex-col space-y-4' app/templates/user/dashboard.html`
Expected: 1개 매칭 (FAB 컨테이너 `<div>` 라인)

- [ ] **Step 2: FAB 블록 전체 교체 (컨테이너 클래스 + 버튼 순서 + 툴팁)**

아래 `old_string`(현재) 전체를 `new_string`(목표)으로 교체한다.

old_string — 현재 블록:
```html
<div class="fixed bottom-8 right-8 z-40 flex flex-col space-y-4">
    <!-- Chatbot FAB -->
    {% if document %}
    <button onclick="toggleChatbot()"
        class="bg-blue-600 text-white p-4 rounded-full shadow-lg hover:bg-blue-700 transition-colors flex items-center justify-center group relative">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
        </svg>
        <span
            class="absolute right-full mr-3 bg-gray-800 text-white text-xs px-2 py-1 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap">
            QnA 챗봇
        </span>
    </button>
    {% endif %}

    <!-- Analysis FAB -->
    <button onclick="startAnalysis()"
        class="bg-indigo-600 text-white p-4 rounded-full shadow-lg hover:bg-indigo-700 transition-colors flex items-center justify-center group relative">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
        </svg>
        <span
            class="absolute right-full mr-3 bg-gray-800 text-white text-xs px-2 py-1 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap">
            분석 시작
        </span>
    </button>
</div>
```

new_string — 목표 블록 (컨테이너: 하단 중앙 + flex-row; 순서: 분석→QnA; 툴팁: 버튼 위 `bottom-full`):
```html
<div class="fixed bottom-8 left-1/2 -translate-x-1/2 z-40 flex flex-row space-x-4">
    <!-- Analysis FAB -->
    <button onclick="startAnalysis()"
        class="bg-indigo-600 text-white p-4 rounded-full shadow-lg hover:bg-indigo-700 transition-colors flex items-center justify-center group relative">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
        </svg>
        <span
            class="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 bg-gray-800 text-white text-xs px-2 py-1 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap">
            분석 시작
        </span>
    </button>

    <!-- Chatbot FAB -->
    {% if document %}
    <button onclick="toggleChatbot()"
        class="bg-blue-600 text-white p-4 rounded-full shadow-lg hover:bg-blue-700 transition-colors flex items-center justify-center group relative">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
        </svg>
        <span
            class="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 bg-gray-800 text-white text-xs px-2 py-1 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap">
            QnA 챗봇
        </span>
    </button>
    {% endif %}
</div>
```

- [ ] **Step 3: 템플릿 컴파일 검증 (Jinja 문법 깨짐 없음)**

Run:
```bash
.venv/bin/python -c "from jinja2 import Environment, FileSystemLoader; e=Environment(loader=FileSystemLoader('app/templates')); e.get_template('user/dashboard.html'); print('dashboard OK')"
```
Expected: `dashboard OK` (예외 없이 출력)

- [ ] **Step 4: 클래스 변경 grep 검증**

Run:
```bash
grep -c 'fixed bottom-8 left-1/2 -translate-x-1/2 z-40 flex flex-row space-x-4' app/templates/user/dashboard.html
grep -c 'fixed bottom-8 right-8 z-40 flex flex-col space-y-4' app/templates/user/dashboard.html
grep -c 'absolute bottom-full mb-2 left-1/2 -translate-x-1/2' app/templates/user/dashboard.html
```
Expected: 첫 번째 `1`, 두 번째 `0`(구식 제거됨), 세 번째 `2`(툴팁 2개)

- [ ] **Step 5: Commit**

```bash
git add app/templates/user/dashboard.html
git commit -m "feat(ui): dashboard FAB를 하단 중앙 가로 배치로 이동 (#101)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: viewer.html FAB → 하단 중앙 가로 배치

**Files:**
- Modify: `app/templates/user/viewer.html` (FAB 컨테이너 `<div>`, 약 :38)

- [ ] **Step 1: 현재 컨테이너 라인 확인**

Run: `grep -n 'fixed bottom-8 right-8 flex flex-col space-y-4 z-40' app/templates/user/viewer.html`
Expected: 1개 매칭 (:38 부근)

- [ ] **Step 2: 컨테이너 클래스 교체**

old_string:
```html
<div class="fixed bottom-8 right-8 flex flex-col space-y-4 z-40">
```
new_string:
```html
<div class="fixed bottom-8 left-1/2 -translate-x-1/2 flex flex-row space-x-4 z-40">
```

(버튼 마크업/순서/`title=` 툴팁은 변경 없음 → 시각 순서 `[평가 보고서][QnA]`)

- [ ] **Step 3: 템플릿 컴파일 검증**

Run:
```bash
.venv/bin/python -c "from jinja2 import Environment, FileSystemLoader; e=Environment(loader=FileSystemLoader('app/templates')); e.get_template('user/viewer.html'); print('viewer OK')"
```
Expected: `viewer OK`

- [ ] **Step 4: 클래스 변경 grep 검증**

Run:
```bash
grep -c 'fixed bottom-8 left-1/2 -translate-x-1/2 flex flex-row space-x-4 z-40' app/templates/user/viewer.html
grep -c 'fixed bottom-8 right-8 flex flex-col space-y-4 z-40' app/templates/user/viewer.html
```
Expected: 첫 번째 `1`, 두 번째 `0`

- [ ] **Step 5: Commit**

```bash
git add app/templates/user/viewer.html
git commit -m "feat(ui): viewer FAB를 하단 중앙 가로 배치로 이동 (#101)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: 시각 스모크 확인 (독립 Tailwind 하니스 + Playwright)

앱 전체(인증·DB·Gemini·업로드)를 띄우지 않고, Tailwind CDN을 로드한 최소 HTML에 두 FAB 블록을 넣어 레이아웃만 시각 확인한다. 베스트-에포트: Playwright가 불가하면 정적 검증으로 대체하고 무엇을 했는지 보고한다.

**Files:**
- Create (임시, 검증 후 삭제): `/tmp/fab_preview.html`

- [ ] **Step 1: 검증용 하니스 작성**

`/tmp/fab_preview.html` 생성 — `<head>`에 `<script src="https://cdn.tailwindcss.com"></script>`, `<body class="relative min-h-screen bg-gray-50">`에 dashboard 목표 FAB 블록(분석+QnA, `{% if %}` 제거한 정적 버전)과, 비교용으로 화면 상단에 "하단 중앙 확인" 안내 텍스트를 둔다.

- [ ] **Step 2: Playwright로 로드 + 스크린샷 (1280x800, 그리고 390x800 모바일 폭)**

`browser_navigate` → `file:///tmp/fab_preview.html`, `browser_resize` 1280x800 후 `browser_take_screenshot`, 이어 390x800로 `browser_resize` 후 재촬영.
Expected: 두 버튼이 화면 **하단 가로 중앙**에 나란히, 데스크톱·모바일 폭 모두 중앙 정렬.

- [ ] **Step 3: 임시 파일 정리**

Run: `rm -f /tmp/fab_preview.html`

- [ ] **Step 4: 결과 보고 (커밋 없음)**

스크린샷으로 하단 중앙·가로 배치 확인 결과를 요약. (Playwright 불가 시: Task1·2의 컴파일+grep 검증 통과로 정적 확인 완료를 명시.)

---

## 최종 단계 (플랜 외, 실행 마무리)

- [ ] `git push -u origin feat/fab-bottom-center`
- [ ] `gh pr create` — 제목 `feat(ui): 분석/QnA FAB 하단 중앙 이동 (#101)`, 본문에 `Closes #101`, 변경 요약, 검증 결과 포함.
