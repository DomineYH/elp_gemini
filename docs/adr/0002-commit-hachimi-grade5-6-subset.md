# HACHIMI-1M은 Grade 5·6 축소 표본을 저장소에 커밋한다

페르소나 원천인 HACHIMI-1M 영어 샘플(74MB, MIT)은 GitHub 단일 파일 한도를 넘고 Git LFS는 이 프로젝트에 전례가 없다. seed 기반 페르소나 추출을 재현하려면 고정 파일이 필요하므로, `scripts/load_personas.py`가 Grade 5·6 행만 걸러 정규화(`Mid`→`Average`, 중복 id 제거)한 `data/personas/hachimi_grade5_6_en.jsonl`을 커밋하고 앱은 런타임에 네트워크를 쓰지 않는다. 학년을 넓히려면 스크립트로 다시 생성해 커밋한다.

결정 근거: https://github.com/DomineYH/elp_gemini/issues/142, https://github.com/DomineYH/elp_gemini/issues/139
