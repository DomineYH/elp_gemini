# 분석 보고서 닫기 → 설문 참여 안내 모달 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 분석 보고서(`#analysisModal`)를 닫을 때 설문 참여 안내 모달을 띄워, 사용자가 설문에 참여하거나 참여 완료를 선택하면 보고서를 닫는다.

**Architecture:** 기존 모달 패턴(Tailwind + `hidden` 클래스 토글 + 인라인 `onclick` Vanilla JS)을 그대로 재사용해 `app/templates/user/dashboard.html` 단일 파일에 `#surveyModal`과 4개의 JS 함수를 추가한다. 분석 모달의 닫기 트리거(X·"닫기")를 `closeAnalysisModal()` → `openSurveyModal()`로 교체하되, `closeAnalysisModal()`은 실제 닫기 동작용으로 유지한다.

**Tech Stack:** Jinja2 템플릿, Tailwind CSS(CDN), Vanilla JavaScript. 백엔드/빌드 변경 없음.

**관련 이슈:** #96 · **설계 문서:** `docs/superpowers/specs/2026-06-05-survey-modal-design.md`

**검증 방식 참고:** 이 프로젝트에는 JS 단위 테스트 하네스가 없다(백엔드만 `pytest`). 모달 토글은 순수 DOM 동작이므로, CLAUDE.md의 단순성·외과적 변경 원칙에 따라 새 테스트 프레임워크를 도입하지 않고 **브라우저 수동 검증**(Task 4)으로 성공 기준을 확인한다.

---

## File Structure

- **Modify only:** `app/templates/user/dashboard.html`
  - 마크업: `#analysisModal`(line 429~458) 바로 뒤, `<!-- Session History Modal -->`(line 460) 앞에 `#surveyModal` 추가
  - 트리거: line 434(상단 X), line 452(하단 "닫기")의 `onclick` 교체
  - 스크립트: `closeAnalysisModal()`(line 1197~1199) 바로 뒤에 신규 함수 4개 추가

---

## Task 1: 설문 모달 마크업 추가

**Files:**
- Modify: `app/templates/user/dashboard.html` (insert after line 458, before line 460)

- [ ] **Step 1: `#analysisModal` 닫는 `</div>` 뒤에 설문 모달 마크업 삽입**

`app/templates/user/dashboard.html`에서 아래 블록(line 458의 `</div>`와 line 460의 `<!-- Session History Modal -->` 사이)을 찾는다:

```html
    </div>
</div>

<!-- Session History Modal -->
```

이것을 다음으로 교체한다 (설문 모달을 사이에 삽입):

```html
    </div>
</div>

<!-- Survey Participation Modal -->
<div id="surveyModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-[60] hidden"
    onclick="if (event.target === this) closeSurveyModal()">
    <div class="bg-white rounded-lg shadow-xl w-full max-w-md m-4">
        <div class="p-4 border-b border-gray-200 flex justify-between items-center bg-indigo-600 text-white rounded-t-lg">
            <h3 class="text-lg font-bold">설문 참여 안내</h3>
            <button onclick="closeSurveyModal()" class="hover:text-gray-200">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24"
                    stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
            </button>
        </div>
        <div class="p-6">
            <p class="text-red-600 font-semibold text-center">
                설문에 참여하셨으면 '설문참여 완료'를 눌러주세요
            </p>
        </div>
        <div class="p-4 border-t border-gray-200 bg-gray-50 flex justify-center space-x-3 rounded-b-lg">
            <button onclick="participateSurvey()"
                class="bg-indigo-600 text-white px-6 py-2 rounded hover:bg-indigo-700 transition-colors">
                설문참여
            </button>
            <button onclick="completeSurvey()"
                class="bg-gray-600 text-white px-6 py-2 rounded hover:bg-gray-700 transition-colors">
                설문참여 완료
            </button>
        </div>
    </div>
</div>

<!-- Session History Modal -->
```

> 참고: 오버레이 `onclick="if (event.target === this) closeSurveyModal()"`는 모달 내부 클릭은 무시하고 **바깥 배경 클릭**일 때만 닫는다. `z-[60]`으로 분석 모달(`z-50`) 위에 표시된다.

- [ ] **Step 2: 마크업 균형 확인 (브라우저 콘솔 불필요, 정적 점검)**

Run:
```bash
grep -n 'id="surveyModal"' app/templates/user/dashboard.html
```
Expected: `#surveyModal`이 1회 출력된다 (line 460 부근).

- [ ] **Step 3: 커밋**

```bash
git add app/templates/user/dashboard.html
git commit -m "feat(report): 설문 참여 안내 모달(#surveyModal) 마크업 추가 (#96)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: 설문 모달 제어 JS 함수 추가

**Files:**
- Modify: `app/templates/user/dashboard.html` (after `closeAnalysisModal()`, ~line 1199)

- [ ] **Step 1: `closeAnalysisModal()` 정의 바로 뒤에 함수 4개 추가**

`app/templates/user/dashboard.html`에서 다음 블록을 찾는다:

```javascript
    function closeAnalysisModal() {
        document.getElementById('analysisModal').classList.add('hidden');
    }

    function printAnalysisReport() {
```

이것을 다음으로 교체한다:

```javascript
    function closeAnalysisModal() {
        document.getElementById('analysisModal').classList.add('hidden');
    }

    function openSurveyModal() {
        document.getElementById('surveyModal').classList.remove('hidden');
    }

    function closeSurveyModal() {
        document.getElementById('surveyModal').classList.add('hidden');
    }

    function participateSurvey() {
        window.open('https://forms.gle/PmnzRSGqUMURr7mJ7', '_blank', 'noopener');
        closeSurveyModal();
        closeAnalysisModal();
    }

    function completeSurvey() {
        closeSurveyModal();
        closeAnalysisModal();
    }

    function printAnalysisReport() {
```

- [ ] **Step 2: 함수 정의 확인 (정적 점검)**

Run:
```bash
grep -nE 'function (openSurveyModal|closeSurveyModal|participateSurvey|completeSurvey)\(' app/templates/user/dashboard.html
```
Expected: 4개 함수가 각각 1회씩 출력된다.

- [ ] **Step 3: 커밋**

```bash
git add app/templates/user/dashboard.html
git commit -m "feat(report): 설문 모달 제어 함수(open/close/participate/complete) 추가 (#96)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: 분석 모달 닫기 트리거를 설문 모달로 교체

**Files:**
- Modify: `app/templates/user/dashboard.html:434` (상단 X 버튼)
- Modify: `app/templates/user/dashboard.html:452` (하단 "닫기" 버튼)

- [ ] **Step 1: 상단 X 버튼 onclick 교체**

다음 한 줄을 찾는다 (분석 모달 헤더, line 434):

```html
            <button onclick="closeAnalysisModal()" class="hover:text-gray-200">
```

다음으로 교체한다:

```html
            <button onclick="openSurveyModal()" class="hover:text-gray-200">
```

> 주의: `closeSurveyModal()`의 X 버튼도 동일한 `class="hover:text-gray-200"`를 갖지만 그 onclick은 `closeSurveyModal()`이므로 위 문자열과 충돌하지 않는다. 정확히 `onclick="closeAnalysisModal()" class="hover:text-gray-200"`인 줄만 교체한다.

- [ ] **Step 2: 하단 "닫기" 버튼 onclick 교체**

다음 블록을 찾는다 (분석 모달 푸터, line 452~455):

```html
            <button onclick="closeAnalysisModal()"
                class="bg-gray-600 text-white px-6 py-2 rounded hover:bg-gray-700 transition-colors">
                닫기
            </button>
```

다음으로 교체한다 (onclick만 변경):

```html
            <button onclick="openSurveyModal()"
                class="bg-gray-600 text-white px-6 py-2 rounded hover:bg-gray-700 transition-colors">
                닫기
            </button>
```

- [ ] **Step 3: 교체 결과 정적 점검**

Run:
```bash
grep -n 'onclick="openSurveyModal()"' app/templates/user/dashboard.html
```
Expected: 2개 줄(상단 X, 하단 "닫기")이 출력된다.

Run:
```bash
grep -n 'onclick="closeAnalysisModal()"' app/templates/user/dashboard.html
```
Expected: **0개** 출력 (분석 모달의 닫기 트리거는 모두 교체됨; `closeAnalysisModal`은 `participateSurvey`/`completeSurvey` 내부에서만 호출됨).

- [ ] **Step 4: 커밋**

```bash
git add app/templates/user/dashboard.html
git commit -m "feat(report): 분석 보고서 X·닫기 버튼이 설문 모달을 열도록 변경 (#96)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: 브라우저 수동 검증

**Files:** 없음 (검증 전용)

이 프로젝트는 JS 단위 테스트 하네스가 없으므로 실제 앱에서 성공 기준을 확인한다.
분석 보고서 모달까지 도달하려면 로그인 → 수업 지도안 업로드 → 분석 실행이 필요하다.

- [ ] **Step 1: 앱 실행 후 분석 보고서 띄우기**

앱을 실행하고(예: 프로젝트의 실행 방법에 따라 Flask 서버 기동), 사용자 계정으로 로그인하여 수업 지도안을 업로드하고 분석을 실행해 **분석 보고서 모달**을 연다.

> 빠른 시각 점검만 필요하면: dashboard 페이지에서 브라우저 콘솔에 `openSurveyModal()`를 입력해 설문 모달 자체를 띄워 레이아웃/문구/버튼을 확인할 수 있다(단, 보고서 닫힘 연동은 실제 보고서가 열린 상태에서 확인해야 함).

- [ ] **Step 2: 성공 기준 체크 (설계 문서 §6)**

다음을 순서대로 확인한다:

- [ ] 보고서 **상단 X** 클릭 → 설문 모달이 보고서 **위**에 표시
- [ ] 보고서 **하단 "닫기"** 클릭 → 설문 모달이 보고서 **위**에 표시
- [ ] 설문 모달에 **붉은색** 안내문 `설문에 참여하셨으면 '설문참여 완료'를 눌러주세요` + 두 버튼 표시
- [ ] **"설문참여"** 클릭 → 새 탭으로 `https://forms.gle/PmnzRSGqUMURr7mJ7` 열림 + 분석 보고서 닫힘
- [ ] **"설문참여 완료"** 클릭 → 설문 모달 + 분석 보고서 모두 닫힘
- [ ] 설문 모달 **배경(오버레이) 클릭** 또는 **X** → 설문 모달만 닫히고 분석 보고서는 그대로 표시
- [ ] 보고서를 다시 닫으면 설문 모달이 **다시** 표시됨

- [ ] **Step 3: 회귀 점검 — 인쇄&저장**

보고서가 열린 상태에서 **"인쇄&저장"** 버튼이 기존대로 동작하는지(인쇄 대화상자 표시) 확인한다. 설문 모달은 평소 `hidden`이라 `@media print`에 영향을 주지 않아야 한다.

- [ ] **Step 4: (선택) 백엔드 회귀 — pytest 베이스라인 비교**

프론트엔드만 변경했으므로 백엔드 테스트 결과는 변하지 않아야 한다. 필요 시:

Run: `python -m pytest`
Expected: 변경 전 베이스라인 대비 신규 실패 없음 (기존 collection/runtime 실패는 PRE-EXISTING).

---

## Self-Review

**1. Spec coverage (설계 문서 §3 요구사항 → 태스크 매핑):**
- 요구 1(X·닫기 → 설문 모달) → Task 3 ✓
- 요구 2(붉은 글씨 + 두 버튼) → Task 1 마크업 ✓
- 요구 3(설문참여: 새 창 + 보고서 닫힘) → Task 2 `participateSurvey()` ✓
- 요구 4(설문참여 완료: 둘 다 닫힘) → Task 2 `completeSurvey()` ✓
- 요구 5(배경/X 취소) → Task 1 오버레이 onclick + 헤더 X ✓
- 요구 6(매번 표시) → 영구 저장 미도입(설계 §5) ✓

**2. Placeholder scan:** TBD/TODO/"적절히 처리" 등 없음. 모든 코드 블록은 실제 코드. ✓

**3. Type/이름 일관성:** `openSurveyModal` / `closeSurveyModal` / `participateSurvey` / `completeSurvey` — 마크업(Task 1)·함수 정의(Task 2)·트리거(Task 3) 전반에서 동일 표기. `#surveyModal` ID 일치. ✓
