# FAB 하단 중앙 이동 설계 (issue #101)

- **이슈**: [#101](https://github.com/DomineYH/elp_gemini/issues/101) — feat(ui): 지도안 업로드 후 분석/QnA FAB 위치 우하단→하단 중앙 이동
- **작성일**: 2026-06-05
- **브랜치**: `feat/fab-bottom-center`

## 배경 / 문제

사용자가 지도안(PDF)을 업로드하면 `분석 시작` / `QnA 챗봇` Floating Action Button(FAB)이 나타난다. 현재 두 버튼은 화면 **우측 하단 모서리**에 세로로 쌓여 고정되어 있는데, 이를 **화면 하단 중앙(가로 중앙 정렬)** 으로 옮긴다.

## 확정된 요구사항 (브레인스토밍 결과)

| 항목 | 결정 |
|------|------|
| 버튼 위치 | 우하단 → **하단 중앙** (가로 중앙 정렬, 하단 고정 유지) |
| 버튼 배치 방향 | **가로 배치** (두 버튼을 나란히) |
| 시각적 순서 | `[분석 시작] [QnA 챗봇]` |
| 챗봇 모달 초기 위치 | **변경 없음** (우측 하단 유지, 드래그·리사이즈 가능) |
| 적용 범위 | **dashboard.html + viewer.html 둘 다** |

## 접근 방식

순수 Tailwind 유틸리티 클래스 변경. JS 변경 없음, 새 CSS 파일/공용 partial 없음.

- 대안으로 두 템플릿이 반복하는 FAB 패턴을 공용 partial로 추출하는 것을 검토했으나, 요청 범위를 벗어난 리팩터링이므로 제외(YAGNI). 클래스 단위 수술적 변경만 수행한다.

## 변경 상세

### 1. `app/templates/user/dashboard.html` (FAB 컨테이너, 약 :353)

- 컨테이너 클래스
  - 변경 전: `fixed bottom-8 right-8 z-40 flex flex-col space-y-4`
  - 변경 후: `fixed bottom-8 left-1/2 -translate-x-1/2 z-40 flex flex-row space-x-4`
- 버튼 순서 재배치: 시각적 `[분석 시작] [QnA 챗봇]` 가 되도록, 항상 렌더링되는 `분석 시작` 버튼을 `{% if document %}` 로 감싼 `QnA 챗봇` 버튼보다 **앞으로** 이동한다. (`{% if document %}` 조건은 그대로 유지)
- 호버 툴팁(`<span>`): 현재 `absolute right-full mr-3`(버튼 왼쪽)으로 되어 있어 가로 배치 시 옆 버튼과 겹친다. **버튼 위쪽**으로 이동: `absolute bottom-full mb-2 left-1/2 -translate-x-1/2`.

### 2. `app/templates/user/viewer.html` (FAB 컨테이너, 약 :38)

- 컨테이너 클래스
  - 변경 전: `fixed bottom-8 right-8 flex flex-col space-y-4 z-40`
  - 변경 후: `fixed bottom-8 left-1/2 -translate-x-1/2 flex flex-row space-x-4 z-40`
- 툴팁 변경 없음 (네이티브 `title=` 속성 사용). DOM 순서 유지 → 시각적 `[평가 보고서] [QnA]`.

### 3. 챗봇 모달 (`dashboard.html` 약 :385)

- **변경 없음.** `fixed bottom-24 right-8` 유지. 버튼이 중앙으로 가도 모달은 우측이라 겹치지 않는다.

## 영향 범위 / 리스크

- 인라인 `onclick` 핸들러(`toggleChatbot()`, `startAnalysis()`, `toggleQnAModal()`)는 버튼 자체에 있어 컨테이너 클래스/DOM 순서 변경의 영향을 받지 않는다.
- FAB 컨테이너를 형제 순서(`firstChild`/`nextSibling`)로 참조하는 JS가 없는지 구현 중 grep으로 확인한다.
- 순수 표현(presentational) 변경이므로 서버 로직·데이터 흐름 영향 없음.

## 검증 (Acceptance / Verification)

표현 변경이라 단위 로직 테스트 대상은 없다. 다음으로 검증한다.

- [ ] 템플릿이 Jinja 오류 없이 렌더링된다(앱 import/템플릿 컴파일).
- [ ] 두 FAB 블록에서 신규 클래스(`left-1/2 -translate-x-1/2`, `flex-row`)가 존재하고 구식 클래스(`right-8`, `flex-col`)가 제거됨을 grep으로 확인.
- [ ] (가능 시) Playwright로 시각 스모크 확인 — 인증+업로드 세션 구성이 가벼우면 수행, 무거우면 정적 렌더 확인으로 대체하고 무엇을 했는지 명시.
- [ ] 데스크톱/모바일 폭 모두에서 버튼이 가로 중앙에 위치하고 콘텐츠를 가리지 않는다.

## 산출물

- 브랜치 `feat/fab-bottom-center`
- PR 본문에 `Closes #101`
