> **⚠️ SUPERSEDED by #91** — This plan designed the email/role/region/UserProfile
> system which has been **removed**. The platform now uses user-chosen `user_id` +
> password login with no email, role, region, career, or UserProfile.
> See `docs/plans/2026-06-04-issue-91-id-auth-email-removal.md`.

# 구현 계획: 일반 사용자 이메일+비밀번호 로그인/등록 전환

- **GitHub Issue**: [#10](https://github.com/DomineYH/elp_gemini/issues/10)
- **작성일**: 2026-05-02
- **목표**: 초대/인증 코드 기반 일반 사용자 로그인을 이메일+비밀번호 기반 등록/로그인으로 전환
- **상세 PRD**: `.omx/plans/prd-email-password-user-auth.md`
- **테스트 명세**: `.omx/plans/test-spec-email-password-user-auth.md`
- **Context snapshot**: `.omx/context/email-password-user-auth-20260502T063939Z.md`

## 핵심 결정

`users`는 인증 주체와 비밀번호 해시를 담당하고, 역할별 연구/분류 메타데이터는 신규 `user_profiles` 1:1 테이블에 분리한다. 일반 사용자 등록 UI는 이메일, 비밀번호, 교사/예비교사별 필수 메타데이터만 받으며 이름/닉네임/전화번호를 받지 않는다.

## 구현 작업 분해

1. **데이터 모델/마이그레이션**
   - 신규 `UserProfile` 모델과 `user_profiles` 테이블 생성.
   - `User.profile` 관계 추가.
   - 기존 관리자/초대코드 사용자는 프로필 없이도 깨지지 않게 처리.

2. **인증 서비스/스키마**
   - 이메일 정규화, 역할별 등록 스키마, 사용자 로그인 인증 메서드 추가.
   - 비밀번호는 기존 bcrypt 유틸을 재사용.
   - 일반 사용자 로그인에 rate limit/lockout 정책 적용 검토 및 최소 IP rate limit 적용.

3. **사용자 로그인/등록 UI**
   - `/login`을 이메일+비밀번호 폼으로 변경.
   - 미등록 이메일은 `/register`로 이동.
   - `/register`에서 교사/예비교사 조건부 필드 제공.

4. **관리자 비밀번호 변경**
   - 관리자 전용 사용자 비밀번호 변경 API/UI 추가.
   - 셀프 비밀번호 재설정은 제공하지 않음.
   - 감사 로그 기록.

5. **테스트/검증**
   - 신규 `tests/test_user_email_password_auth.py` 작성.
   - 기존 관리자 로그인 회귀 테스트 실행.
   - 템플릿에 직접 식별 개인정보 필드가 없는지 검증.

## 병렬화 제안

- Lane A: 모델/마이그레이션
- Lane B: 인증 서비스/스키마
- Lane C: 사용자 라우트/템플릿
- Lane D: 관리자 비밀번호 변경/사용자 관리
- Lane E: 테스트/검증

선행 의존성은 Lane A의 모델/필드명 확정이며, 이후 B/C/D/E는 병렬 진행 가능하다.

## 인수 기준 요약

- 초대 코드 없이 이메일+비밀번호로 로그인 가능.
- 미등록 이메일은 등록 흐름으로 이동.
- 교사는 지정 지역+경력 연수+비밀번호로 등록.
- 예비교사는 지정 대학교지역+학년+비밀번호로 등록.
- 비밀번호는 해시로 저장.
- 비밀번호 분실은 관리자 변경만 가능.
- 기존 관리자 로그인/보안 테스트가 회귀 없이 통과.
- 이메일 외 직접 식별 개인정보 입력 필드 없음.

## 검증 명령

```bash
pytest tests/test_user_email_password_auth.py
pytest tests/test_admin_login_bruteforce.py tests/test_login_admin_routing.py
pytest tests/unit/test_auth_middleware.py
python -m compileall app
```

## GitHub Issue

- [#10 일반 사용자 이메일+비밀번호 로그인/등록 전환 계획](https://github.com/DomineYH/elp_gemini/issues/10)
