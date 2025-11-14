# 문서 동기화 문제 해결 테스트 시나리오

## 수정 사항 요약

### 1. 로그인 로직 수정 (`app/services/auth_service.py`)
- **기존:** username과 nickname이 모두 일치해야 기존 사용자로 인식
- **수정:** username만으로 사용자 식별, nickname은 변경 가능
- **효과:** 동일한 username으로 로그인 시 항상 같은 계정 사용

### 2. Vector DB 문서 삭제 메서드 수정
- `file_search_service.py`: delete_document 메서드 파라미터 및 API 호출 수정
- `user_docs.py`: 호출 시 파라미터 단순화

### 3. 데이터베이스 정리
- 중복 사용자 계정 삭제 (user_id > 2)
- 모든 문서 및 업로드 파일 삭제
- 깨끗한 상태에서 시작

## 테스트 시나리오

### 시나리오 1: 기본 로그인 및 문서 업로드
1. **로그인**
   - Username: `test_user`
   - Nickname: `테스트 사용자`
   - ✅ 예상: 새 사용자 생성 (user_id=6)

2. **문서 업로드**
   - 제목: `테스트 문서 1`
   - 파일: PDF 파일
   - ✅ 예상: Vector DB 업로드 성공, status='ready'

3. **문서 목록 확인**
   - ✅ 예상: 대시보드에 "테스트 문서 1" 표시

### 시나리오 2: 재로그인 후 문서 확인 (핵심 테스트)
1. **로그아웃**

2. **재로그인 (동일한 username, 다른 nickname)**
   - Username: `test_user` (동일)
   - Nickname: `변경된 닉네임` (다름)
   - ✅ 예상: 기존 사용자로 로그인 (user_id=6), nickname 업데이트

3. **문서 목록 확인**
   - ✅ 예상: 이전에 업로드한 "테스트 문서 1" 여전히 표시됨
   - ❌ 기존 문제: 새 사용자 생성으로 문서가 보이지 않음

### 시나리오 3: 추가 문서 업로드
1. **문서 업로드**
   - 제목: `테스트 문서 2`
   - ✅ 예상: 동일한 user_id로 저장

2. **문서 목록 확인**
   - ✅ 예상: "테스트 문서 1", "테스트 문서 2" 모두 표시

### 시나리오 4: 문서 삭제
1. **"테스트 문서 1" 삭제**
   - ✅ 예상: Vector DB에서도 삭제, Local DB status='deleted'

2. **문서 목록 확인**
   - ✅ 예상: "테스트 문서 2"만 표시

## 검증 포인트

### DB 레벨 검증
```sql
-- 사용자 수 확인 (test_user 1개만 생성되어야 함)
SELECT COUNT(*) FROM users WHERE username LIKE 'test_user%';  -- 예상: 1

-- 문서와 사용자 연결 확인
SELECT u.username, d.title, d.status
FROM documents d
JOIN users u ON d.user_id = u.id
WHERE u.username = 'test_user';
```

### 로그 레벨 검증
- 로그인 시 "로그인 성공" 메시지에 user_id 확인
- 재로그인 시 동일한 user_id 사용 확인
- 문서 업로드 시 "문서 업로드 완료" 메시지 확인
- Vector DB 업로드 성공 로그 확인

## 성공 기준

1. ✅ 동일한 username으로 로그인 시 항상 같은 계정 사용
2. ✅ nickname 변경 시에도 문서 유지
3. ✅ 재로그인 후 이전 문서 목록 정상 표시
4. ✅ Vector DB와 Local DB 동기화 정상 작동
5. ✅ 중복 사용자 계정 생성 안 됨

## 실행 방법

```bash
# 1. 서버 실행
cd /mnt/d/dev/elp_gemini
python main.py

# 2. 브라우저에서 테스트
http://localhost:8001

# 3. DB 상태 확인
sqlite3 data/app.db "SELECT * FROM users; SELECT * FROM documents;"
```
