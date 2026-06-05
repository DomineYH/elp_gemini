# 분석 보고서 - 인쇄 버튼을 "인쇄&저장"(PDF 저장)으로 변경

- 작성일: 2026-06-05
- 작성자: Claude (with DomineYH)
- 관련 코드: `app/templates/user/dashboard.html`
- 관련 이슈: #94

## 1. 배경

수업 지도안 분석 보고서는 대시보드(`app/templates/user/dashboard.html`)의 모달(`#analysisModal`)에 표시된다. 보고서 본문은 서버에서 받은 Markdown을 클라이언트에서 `marked.js`로 렌더해 `#analysisContent`에 넣는다.

현재 모달 하단에는 **`인쇄`** 버튼이 있고, 클릭 시 `printAnalysisReport()` → `window.print()`를 호출한다. 출력 레이아웃은 같은 파일의 `@media print` CSS 블록(line 118+)이 담당한다.

사용자는 이 버튼을 PDF 저장 용도로 쓰고 싶어 하며, 버튼 라벨을 의도에 맞게 바꾸고 PDF로 저장할 때 파일명이 의미 있게 제안되기를 원한다.

## 2. 목표 및 비목표

### 2.1 목표

- 모달 하단 버튼의 라벨을 `인쇄` → **`인쇄&저장`** 으로 변경한다.
- 버튼 클릭 시 브라우저 인쇄 대화상자가 열리고, 사용자가 대상으로 "PDF로 저장"을 선택하면 보고서가 PDF로 저장된다(기존 `window.print()` 동작 유지).
- "PDF로 저장" 시 브라우저가 제안하는 기본 파일명이 `수업지도안_분석보고서_YYYY-MM-DD` 형태가 되도록 `document.title`을 인쇄 직전 변경하고 인쇄 후 원복한다.

### 2.2 비목표

- 클라이언트/서버 PDF 생성 라이브러리(html2pdf.js, WeasyPrint 등)는 도입하지 않는다. (사용자가 `window.print()` 방식을 선택함)
- `@media print` CSS 블록의 출력 레이아웃 로직은 변경하지 않는다.
- 백엔드 라우트/의존성은 변경하지 않는다.
- `dashboard.html` 외 다른 템플릿은 변경하지 않는다(인쇄 버튼은 이 파일에만 존재).

## 3. 설계

### 3.1 변경 대상 (단일 파일: `app/templates/user/dashboard.html`)

**(1) 버튼** (현재 line 445–451)
- 텍스트 `인쇄` → `인쇄&저장`
- 아이콘: 기존 프린터 SVG **유지** (라벨에 "인쇄"가 포함되고 실제로 인쇄 대화상자를 띄우므로 정직함, 변경 최소화)
- `onclick` 핸들러: 기존 `printAnalysisReport()` **이름 유지** (여전히 `window.print()`를 호출하므로 의미가 정확하고 변경 범위를 최소화)

**(2) 함수** `printAnalysisReport()` (현재 line 1201–1211)
- 모달 열림 가드 및 알림(`인쇄할 보고서가 없습니다.`)은 그대로 유지한다.
- `window.print()` 호출 직전에 현재 `document.title`을 저장하고, `수업지도안_분석보고서_${YYYY-MM-DD}`로 교체한다.
- 인쇄 대화상자가 닫히면 `window.addEventListener('afterprint', ...)`(1회성)로 원래 `document.title`을 복원한다.
- 날짜는 클라이언트 `new Date()`로 생성한다(로컬 날짜 기준, `YYYY-MM-DD`).

**(3) CSS 주석** (line 118)
- `/* 인쇄용 스타일 */` → `/* PDF 저장(인쇄)용 스타일 */` (주석만, 규칙은 불변)

### 3.2 동작 흐름

```
[사용자] "인쇄&저장" 클릭
   ↓
printAnalysisReport()
   ↓ 모달 닫혀있으면 alert 후 종료
   ↓ prevTitle = document.title
   ↓ document.title = "수업지도안_분석보고서_2026-06-05"
   ↓ window.print()  → 브라우저 인쇄 대화상자 (대상: "PDF로 저장" 선택 가능)
   ↓ afterprint 이벤트 → document.title = prevTitle (원복)
```

### 3.3 파일명 결정

- 형식: `수업지도안_분석보고서_YYYY-MM-DD`
- 보고서 원본 파일명 추출은 하지 않는다(YAGNI). 모달 콘텐츠는 Markdown 문자열만 받고 안정적인 파일명 메타데이터가 없으므로, 고정 접두사 + 날짜로 충분하다.

## 4. 에러 처리 / 엣지 케이스

- **모달이 닫힌 상태에서 호출**: 기존 가드 유지 — `alert('인쇄할 보고서가 없습니다.')` 후 반환. 이 경우 `document.title`은 변경하지 않는다.
- **`afterprint` 미발화 브라우저**: `afterprint`는 모든 주요 브라우저(Chrome/Edge/Firefox/Safari)에서 지원되므로 별도 폴백 타이머는 두지 않는다. 설령 원복이 누락되어도 영향은 탭 제목뿐이며, 다음 페이지 이동/리로드 시 정상화된다.
- **여러 번 클릭**: `afterprint` 리스너는 `{ once: true }`로 등록해 중복 누적을 방지한다.

## 5. 검증

프론트엔드(템플릿/JS) 전용 변경이며 프론트엔드 자동 테스트 하니스가 없다.

- 정적 확인: 변경 후 `dashboard.html`에서 (a) 버튼 라벨이 `인쇄&저장`인지, (b) `document.title` 저장/복원 로직 존재, (c) 잔존 오타/깨짐 없는지 확인.
- 수동 확인(가능 시): 앱 실행 → 분석 보고서 모달 열기 → "인쇄&저장" 클릭 → 인쇄 미리보기에서 레이아웃 정상 + 대상 "PDF로 저장" 선택 시 제안 파일명이 `수업지도안_분석보고서_YYYY-MM-DD`인지 확인.
- 백엔드 미변경이므로 기존 `python -m pytest` 결과(사전 존재 실패 포함)는 영향받지 않는다.
