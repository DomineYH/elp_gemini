# 분석 보고서 닫기 → 설문 참여 안내 모달 설계

- 작성일: 2026-06-05
- 대상 파일: `app/templates/user/dashboard.html`
- 관련 기능: 수업 지도안 분석 보고서(`#analysisModal`)

## 1. 배경 / 목적

사용자가 분석 보고서를 닫을 때 설문조사 참여를 유도한다. 보고서를 닫는
모든 경로(상단 X 버튼, 하단 "닫기" 버튼)에서 설문 참여 안내 모달을 띄우고,
설문 참여 또는 참여 완료 시 보고서를 닫는다.

## 2. 현재 동작 (변경 전)

`app/templates/user/dashboard.html`

- 분석 모달 마크업: line 429~458 (`#analysisModal`)
  - 상단 X 버튼(line 434): `onclick="closeAnalysisModal()"`
  - 하단 "닫기" 버튼(line 452): `onclick="closeAnalysisModal()"`
- `closeAnalysisModal()`(line 1197~1199): 모달에 `hidden` 클래스 추가로 숨김
- 모달은 `hidden` 클래스 토글로 표시/숨김 제어 (Vanilla JS + Tailwind)

## 3. 요구사항

1. 분석 보고서 상단 X 버튼과 하단 "닫기" 버튼을 누르면, 보고서를 바로 닫지
   않고 **설문 참여 안내 모달**이 열린다.
2. 설문 모달 구성:
   - **붉은색 글씨** 안내문: `설문에 참여하셨으면 '설문참여 완료'를 눌러주세요`
   - 버튼: `설문참여`, `설문참여 완료`
3. **설문참여** 버튼:
   - `https://forms.gle/PmnzRSGqUMURr7mJ7` 를 **새 창/탭**으로 연다.
   - 분석 보고서를 닫는다.
4. **설문참여 완료** 버튼: 설문 모달과 분석 보고서를 **모두 닫는다**. (합의됨)
5. **취소 경로**: 설문 모달의 **배경(오버레이) 클릭** 또는 **X 버튼**으로
   설문 모달만 닫고 분석 보고서로 돌아갈 수 있다. (합의됨)
6. 매번 보고서를 닫을 때마다 설문 모달이 표시된다. ("다시 보지 않기" 영구
   저장은 하지 않음 — 합의됨)

## 4. 설계 (Approach A: 기존 모달 패턴 재사용)

기존 분석/챗봇 모달과 동일한 패턴(Tailwind + `hidden` 토글 + Vanilla JS)으로
설문 모달을 추가한다. 범용 모달 컴포넌트화(B)나 `confirm()`(C)는 각각 과한
추상화·요구 미충족으로 배제.

### 4.1 트리거 변경 (분석 모달)

- 상단 X 버튼(line 434): `onclick="closeAnalysisModal()"` → `onclick="openSurveyModal()"`
- 하단 "닫기" 버튼(line 452): `onclick="closeAnalysisModal()"` → `onclick="openSurveyModal()"`
- `closeAnalysisModal()` 함수는 **유지**한다 (실제 보고서 닫기 동작에 재사용).

### 4.2 설문 모달 마크업 (`#surveyModal`)

- `#analysisModal`의 형제로 추가.
- 오버레이 + 중앙 정렬, 기본 `hidden`.
- `z-[60]` 으로 분석 모달(`z-50`) **위**에 표시되도록 한다.
- 오버레이(바깥 영역) 클릭 시 설문 모달만 닫음 → `closeSurveyModal()`
  (이벤트 타겟이 오버레이 자신일 때만; `viewer.html`의 배경 클릭 패턴 참고).
- 헤더에 작은 X 버튼 → `closeSurveyModal()`.
- 본문: 붉은색 안내문 `설문에 참여하셨으면 '설문참여 완료'를 눌러주세요`
  (예: `text-red-600 font-semibold`).
- 푸터: `설문참여`, `설문참여 완료` 두 버튼.

```
┌───────────────────────────────┐
│  설문 참여 안내            [X] │
├───────────────────────────────┤
│ (붉은 글씨)                    │
│ 설문에 참여하셨으면            │
│ '설문참여 완료'를 눌러주세요    │
│                               │
│   [ 설문참여 ] [ 설문참여 완료 ]  │
└───────────────────────────────┘
   바깥(오버레이) 클릭 시 취소
```

### 4.3 신규 JavaScript 함수

| 함수 | 동작 |
|------|------|
| `openSurveyModal()` | `#surveyModal`에서 `hidden` 제거 (분석 보고서는 뒤에 유지) |
| `closeSurveyModal()` | `#surveyModal`에 `hidden` 추가 (설문 모달만 닫음, 보고서 유지) |
| `participateSurvey()` | `window.open('https://forms.gle/PmnzRSGqUMURr7mJ7', '_blank', 'noopener')` → `closeSurveyModal()` → `closeAnalysisModal()` |
| `completeSurvey()` | `closeSurveyModal()` → `closeAnalysisModal()` |

버튼 매핑:
- `설문참여` → `participateSurvey()`
- `설문참여 완료` → `completeSurvey()`
- X / 오버레이 클릭 → `closeSurveyModal()`

### 4.4 동작 흐름 요약

| 트리거 | 결과 |
|--------|------|
| 분석 모달 X / "닫기" | 설문 모달 열림 (보고서는 뒤에 유지) |
| 설문 모달 — 설문참여 | 새 창 오픈 + 설문 모달 닫힘 + 보고서 닫힘 |
| 설문 모달 — 설문참여 완료 | 설문 모달 닫힘 + 보고서 닫힘 |
| 설문 모달 — X / 배경 클릭 | 설문 모달만 닫힘 → 보고서 유지 |

## 5. 부수 고려사항 / 비범위

- **인쇄 CSS**: 설문 모달은 평소 `hidden`이므로 `@media print`(보고서 PDF
  저장, line 118~230)에 영향 없음. 별도 처리 불필요.
- **새 창 보안**: `window.open(..., 'noopener')`로 연다.
- **비범위**: "다시 보지 않기" 영구 저장(localStorage 등), 설문 참여 여부의
  서버 기록, 백엔드 변경은 하지 않는다. 변경은 `dashboard.html` 단일 파일에
  한정한다.

## 6. 성공 기준 (검증)

1. 보고서 상단 X 클릭 → 설문 모달이 보고서 위에 표시된다.
2. 보고서 하단 "닫기" 클릭 → 설문 모달이 보고서 위에 표시된다.
3. 설문 모달에 붉은색 안내문과 두 버튼이 보인다.
4. "설문참여" 클릭 → 새 탭에 설문 URL이 열리고, 분석 보고서가 닫힌다.
5. "설문참여 완료" 클릭 → 설문 모달과 분석 보고서가 모두 닫힌다.
6. 설문 모달 배경/X 클릭 → 설문 모달만 닫히고 분석 보고서는 그대로 보인다.
7. 보고서를 다시 닫으면 설문 모달이 다시 표시된다.
