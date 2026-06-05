# 분석 보고서 "인쇄&저장"(PDF 저장) 버튼 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 대시보드 분석 보고서 모달의 `인쇄` 버튼을 `인쇄&저장`으로 바꾸고, `window.print()` 시 "PDF로 저장" 기본 파일명이 `수업지도안_분석보고서_YYYY-MM-DD`로 제안되게 한다.

**Architecture:** 단일 Jinja 템플릿(`app/templates/user/dashboard.html`)의 버튼 라벨, 클릭 핸들러 함수, CSS 주석만 수정한다. 새 라이브러리·백엔드·의존성 변경 없음. 출력 레이아웃은 기존 `@media print` CSS를 그대로 재사용한다.

**Tech Stack:** FastAPI + Jinja2 템플릿, 바닐라 JS, 브라우저 `window.print()` / `afterprint` 이벤트.

> **테스트 노트:** 이 프로젝트에는 프론트엔드(JS/템플릿) 자동 테스트 하니스가 없다. 따라서 검증은 (1) 정적 grep 확인과 (2) 선택적 수동 앱 확인으로 수행한다. 백엔드 미변경이므로 `python -m pytest`의 사전 존재 실패는 영향받지 않는다.

---

### Task 1: 버튼 라벨 변경 (`인쇄` → `인쇄&저장`)

**Files:**
- Modify: `app/templates/user/dashboard.html` (현재 버튼 line 445–451)

- [ ] **Step 1: 버튼 텍스트 교체**

`onclick="printAnalysisReport()"` 버튼의 본문 텍스트만 `인쇄` → `인쇄&저장`으로 바꾼다. 프린터 SVG 아이콘과 클래스, onclick 핸들러명은 유지한다.

변경 전(텍스트 줄):
```html
                인쇄
            </button>
```

변경 후:
```html
                인쇄&저장
            </button>
```

> 주의: 이 텍스트 줄은 닫는 `</svg>` 바로 다음, `onclick="printAnalysisReport()"` 버튼 안에 있는 것이어야 한다(모달 하단 버튼). 다른 `인쇄` 문자열(주석/JS)과 혼동하지 말 것.

- [ ] **Step 2: 정적 확인 — 버튼 라벨 적용**

Run: `grep -n "인쇄&저장" app/templates/user/dashboard.html`
Expected: 버튼 본문 라인 1건 매치.

Run: `grep -n ">\s*인쇄\s*<\|^\s*인쇄\s*$" app/templates/user/dashboard.html`
Expected: 단독 `인쇄` 버튼 라벨이 더 이상 없음(매치 0건). (주석 `/* ... 인쇄 ... */`는 별개)

---

### Task 2: 클릭 핸들러에 파일명 제안 로직 추가

**Files:**
- Modify: `app/templates/user/dashboard.html` (현재 함수 line 1201–1211)

- [ ] **Step 1: `printAnalysisReport()` 함수 본문 교체**

기존 함수 전체를 아래로 교체한다. 모달 가드/알림은 유지하고, `window.print()` 직전에 `document.title`을 보고서 파일명으로 바꾼 뒤 `afterprint`(1회성)로 원복한다.

변경 전:
```javascript
    function printAnalysisReport() {
        // 인쇄 전 모달이 열려있는지 확인
        const modal = document.getElementById('analysisModal');
        if (modal.classList.contains('hidden')) {
            alert('인쇄할 보고서가 없습니다.');
            return;
        }

        // 인쇄 실행
        window.print();
    }
```

변경 후:
```javascript
    function printAnalysisReport() {
        // 인쇄&저장 전 모달이 열려있는지 확인
        const modal = document.getElementById('analysisModal');
        if (modal.classList.contains('hidden')) {
            alert('인쇄할 보고서가 없습니다.');
            return;
        }

        // "PDF로 저장" 시 제안 파일명이 의미 있도록 document.title을 임시 변경
        const now = new Date();
        const yyyy = now.getFullYear();
        const mm = String(now.getMonth() + 1).padStart(2, '0');
        const dd = String(now.getDate()).padStart(2, '0');
        const prevTitle = document.title;
        document.title = `수업지도안_분석보고서_${yyyy}-${mm}-${dd}`;

        // 인쇄 대화상자 종료 후 원래 제목 복원 (1회성)
        window.addEventListener('afterprint', () => {
            document.title = prevTitle;
        }, { once: true });

        // 인쇄&저장 실행 (대상에서 "PDF로 저장" 선택 가능)
        window.print();
    }
```

- [ ] **Step 2: 정적 확인 — 로직 적용**

Run: `grep -n "수업지도안_분석보고서_" app/templates/user/dashboard.html`
Expected: 1건 매치(템플릿 리터럴).

Run: `grep -n "afterprint" app/templates/user/dashboard.html`
Expected: 1건 매치.

Run: `grep -n "window.print()" app/templates/user/dashboard.html`
Expected: 1건 매치(함수 마지막 줄).

---

### Task 3: CSS 주석 정리

**Files:**
- Modify: `app/templates/user/dashboard.html:118`

- [ ] **Step 1: 주석 문구 교체**

변경 전:
```css
/* 인쇄용 스타일 */
```

변경 후:
```css
/* PDF 저장(인쇄)용 스타일 */
```

- [ ] **Step 2: 정적 확인**

Run: `grep -n "PDF 저장(인쇄)용 스타일" app/templates/user/dashboard.html`
Expected: 1건 매치.

---

### Task 4: 선택적 수동 확인 + 커밋

**Files:**
- Modify: (없음 — 검증/커밋 단계)

- [ ] **Step 1: (선택) 앱 실행 후 시각 확인**

앱을 띄울 수 있으면: 대시보드에서 분석 보고서 모달을 연 뒤 하단 버튼이 `인쇄&저장`인지 확인하고 클릭 → 인쇄 미리보기 레이아웃이 기존과 동일한지, 대상에서 "PDF로 저장" 선택 시 제안 파일명이 `수업지도안_분석보고서_YYYY-MM-DD`인지 확인한다. (헤드리스/실행 불가 환경이면 이 단계는 건너뛰고 정적 확인 결과로 갈음한다.)

- [ ] **Step 2: 변경 전체 diff 확인**

Run: `git diff app/templates/user/dashboard.html`
Expected: 버튼 텍스트 1줄, 함수 본문, CSS 주석 1줄 외 다른 변경 없음(서지컬 변경).

- [ ] **Step 3: 커밋**

```bash
git add app/templates/user/dashboard.html
git commit -m "feat(report): 분석 보고서 '인쇄' 버튼을 '인쇄&저장'(PDF 저장)으로 변경 (#94)

- 버튼 라벨 인쇄 → 인쇄&저장
- window.print() 직전 document.title을 수업지도안_분석보고서_YYYY-MM-DD로 변경, afterprint로 원복
- @media print CSS 주석 정리

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage:**
- 스펙 §2.1 라벨 변경 → Task 1 ✓
- 스펙 §2.1 window.print() 유지 + PDF 저장 → Task 2 (window.print 유지) ✓
- 스펙 §2.1 파일명 자동 제안(document.title + afterprint) → Task 2 ✓
- 스펙 §3.1(3) CSS 주석 정리 → Task 3 ✓
- 스펙 §5 검증(정적 grep + 수동) → Task 1–4 각 Step 및 Task 4 ✓
- 비목표(라이브러리/백엔드/레이아웃 미변경) → 어떤 Task도 위반하지 않음 ✓

**2. Placeholder scan:** TBD/TODO/"적절히 처리" 등 없음. 모든 코드 단계에 실제 코드 포함. ✓

**3. Type consistency:** 함수명 `printAnalysisReport`로 Task 1(버튼 onclick)·Task 2(정의) 일치. `afterprint`/`document.title` 사용 일관. ✓
