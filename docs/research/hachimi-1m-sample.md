# HACHIMI-1M 샘플 데이터셋 사실 확인 (#131)

조사일: 2026-10-21. 대상 커밋: Hugging Face `sii-research/HACHIMI-1M` `main` = `ff2ae731d7202f3f4ab483452dc85763ada5d321` (lastModified 2026-03-27T08:23:19Z).
두 JSONL 파일을 인증 없이 내려받아 `python3 -I`로 전수 집계했다. 데이터 파일은 저장소에 커밋하지 않았다.

출처:
- 데이터셋 카드: https://huggingface.co/datasets/sii-research/HACHIMI-1M
- 메타데이터 API: https://huggingface.co/api/datasets/sii-research/HACHIMI-1M
- 파일 트리 API: https://huggingface.co/api/datasets/sii-research/HACHIMI-1M/tree/main
- 커밋 이력 API: https://huggingface.co/api/datasets/sii-research/HACHIMI-1M/commits/main
- 논문: https://arxiv.org/abs/2603.04855 (HACHIMI: Scalable and Controllable Student Persona Generation via Orchestrated Agents, Jiang·Tan·Yin·Leng·Zhou, 2026-03-05)
- 코드: https://github.com/ZeroLoss-Lab/HACHIMI (MIT, `LICENSE` 저작권 표기 "Copyright (c) 2025 HACHIMI Contributors")

## 1. 실존 여부·파일명·크기·레코드 수

| 항목 | 사실 | 출처 |
| --- | --- | --- |
| 데이터셋 존재 | 공개(`private: false`), 비게이트(`gated: false`), 인증 없이 접근 가능 | 메타데이터 API |
| `sample_data/` 디렉터리 | **없음**. 트리 API `tree/main/sample_data` 응답: `{"error":"sample_data does not exist on \"main\""}`. README "File Structure" 절의 `sample_data/…` 표기는 실제 트리와 다르다 | 파일 트리 API, README |
| 영어 샘플 | `merged_students_10k_EN.jsonl` (저장소 **루트**), 74,252,201 B (약 70.8 MiB), LFS, sha256 `c6aedd3fdf4ded00ae36fa81ca5767f6e6b1375bd54aad202eb597bbe16efa58` | 파일 트리 API, 다운로드 후 `sha256sum` 일치 |
| 중국어 샘플 | `merged_students_10k.jsonl` (저장소 루트), 51,358,603 B (약 49.0 MiB), LFS, sha256 `81fae184ab5feedff5153cae32ca25da2105473d355e125a48ff8fcc095a472e` | 동일 |
| 기타 파일 | `README.md`(10,022 B), `.gitattributes`, `ceps_results.jpg`, `pisa_results.png` | 파일 트리 API |
| 레코드 수 (EN) | **9,936**행 (README의 "10,000"과 불일치). 파싱 실패 0. `id` 범위 1~10000, 고유 id 9,903개, **중복 id 33개**(62~94, 각 2회, 내용은 서로 다름), 누락 id 97개 | 전수 집계 |
| 레코드 수 (CN) | **10,000**행, id 1~10000 모두 고유, 파싱 실패 0 | 전수 집계 |
| 최대 행 길이 (EN) | 15,234자 | 전수 집계 |
| 전체 1M | 미공개. HF README: "The full dataset and source code will be open-sourced soon." GitHub README: 샘플은 peer review 재현 확인용이며 전체(1M+)는 심사 후 "our platform"으로 공개 예정 | HF README, GitHub README 191행 |

## 2. 라이선스·출처 표기

- HF 카드 frontmatter `license: mit`, 본문 "This dataset is released under **MIT License**". HF 저장소 안에 `LICENSE` 파일은 없다(파일 트리 기준).
- GitHub 코드 저장소 `LICENSE`: 표준 MIT 본문, 저작권 "Copyright (c) 2025 HACHIMI Contributors".
- MIT 조건: 저작권 고지와 허가 고지를 사본에 포함. 별도의 추가 표기 요구는 HF 카드에 없다. 카드의 "Important Notes" 3항은 "Do not use data for discriminatory assessment or harmful purposes"를 요청하나 라이선스 조항은 아니다.
- 인용 요청(HF 카드 BibTeX):
  `@article{jiang2026hachimi, title={HACHIMI: Scalable and Controllable Student Persona Generation via Orchestrated Agents}, author={Jiang, Yilin and Tan, Fei and Yin, Xuanyu and Leng, Jing and Zhou, Aimin}, journal={arXiv preprint arXiv:2603.04855}, year={2026}}`
- 생성 모델: 논문 초록 "All personas are generated with Qwen2.5-72B". 합성 데이터이며 카드에 따르면 실명은 제거됨.

## 3. 실제 스키마 (EN, 9,936행 전부 동일 키 집합·순서)

| 키 | 타입 | 비고 |
| --- | --- | --- |
| `id` | int | 고유하지 않음(위 참조) |
| `age` | int | 6~18 |
| `gender` | str | `female` 5,039 / `male` 4,897 (소문자) |
| `grade` | str | 자유 문자열, 25종(아래 4절) |
| `development_stage` | dict | 키 `piaget_cognitive_stage`, `erikson_psychosocial_stage`, `kohlberg_moral_stage` (전 행 동일) |
| `strong_subjects` | list[str] | |
| `weak_subjects` | list[str] | |
| `academic_level` | str | `"<범주>: <설명>"` 형식, 8종(아래 5절) |
| `personality` | str | |
| `values` | str | |
| `social_relationships` | str | |
| `creativity` | str | |
| `mental_health` | str | |
| `sampling_constraints` | dict | 키 `grade`, `gender`, `strength_subject_bias`(list), `target_academic_level`. `target_academic_level` 분포는 `academic_level`과 동일 |

CN 파일 키: `id, 年龄, 性别, 年级, 发展阶段{皮亚杰认知发展阶段, 埃里克森心理社会发展阶段, 科尔伯格道德发展阶段}, 擅长科目, 薄弱科目, 学术水平, 人格, 价值观, 社交关系, 创造力, 心理健康, _采样约束{年级, 性别, 优势学科偏向, 目标学术水平}`. 1행은 `科尔柏格道德发展阶段`(오타 키).

### PRD F3/F16 전제와의 대조

| PRD 전제 | 실제 (EN 파일) | 일치 |
| --- | --- | --- |
| `developmental_stage` | `development_stage` | 키 이름 불일치 (README 예시는 `developmental_stage`로 적혀 있으나 파일은 다름) |
| `strengths[]` / `weaknesses[]` | `strong_subjects[]` / `weak_subjects[]` | 키 이름 불일치 (README 예시 `strengths`/`weaknesses`와도 다름) |
| `developmental_stage{piaget/erikson/kohlberg}` | `{piaget_cognitive_stage, erikson_psychosocial_stage, kohlberg_moral_stage}` | 구조 일치, 키 이름은 긴 형태 |
| `id, age, gender, grade, academic_level, personality, values, social_relationships, creativity, mental_health` | 동일 | 일치 |
| 추가 필드 없음 | `sampling_constraints` 1개 추가 | 불일치 |
| `academic_level` = High/Medium/Low/Poor 4값 | 접두 5종: `High` 2,522 / `Average` 2,416 / `Low` 2,585 / `Poor` 2,365 / `Mid` 48. **`Medium` 문자열은 0건**. 문자열 전체로는 8종 | 불일치 (범주 수 4는 맞으나 표기는 `Average`, 소수 `Mid`) |
| `"High: ..."` 접두 형식 | 전 행 `"<범주>: <설명>"` 형식 | 일치 |
| `gender` 값 | README 예시 `Female`, 파일은 `female`(소문자) | README와 불일치 |

## 4. grade 분포

EN `grade` 원문 값 25종(전수):

| 값 | 건수 |
| --- | --- |
| Grade 1 (Primary) | 798 |
| Grade 2 (Primary) | 792 |
| Grade 3 (Primary) | 767 |
| Grade 4 (Primary) | 811 |
| **Grade 5 (Primary)** | **801** |
| **Grade 6 (Primary)** | **939** |
| Grade 7 (Junior High) | 827 |
| Grade 8 (Junior High) | 769 |
| Grade 9 (Junior High) | 813 |
| Grade 10 (Senior High) | 850 |
| Grade 11 (Senior High) | 805 |
| Grade 12 (Senior High) | 797 |
| English: First Grade | 24 |
| Fifth grade | 19 |
| English: Senior Year of High School or Grade 12 | 16 |
| English: Freshman in High School | 15 |
| English: Second Grade | 15 |
| English: Third grade | 14 |
| English: Grade 7 (or First Year of Junior High School) | 13 |
| Fourth grade | 11 |
| English: Sophomore in high school | 10 |
| Sixth grade | 10 |
| English: Grade 8 (or Second Year of Junior High School) | 10 |
| English: Grade 9 (Junior 3) | 9 |
| 六年级（因学业原因留级一年，现12岁） | 1 (id 9577, age 12, Poor) |

학년 번호로 정규화하면 1: 822, 2: 807, 3: 781, 4: 822, **5: 820**, **6: 950**(939 + 10 + 중국어 1건), 7: 840, 8: 779, 9: 822, 10: 865, 11: 815, 12: 813. 정확히 `Grade 5 (Primary)`/`Grade 6 (Primary)` 문자열만 쓰면 801 / 939.

CN `年级`: 一年级 830, 二年级 813, 三年级 789, 四年级 826, **五年级 824**, **六年级 949**(+ 留级 1), 初一 844, 初二 786, 初三 825, 高一 870, 高二 824, 高三 819. 13종으로 EN보다 정규적이다.

## 5. academic_level 분포

EN 문자열 8종(전수):

| 값 | 건수 |
| --- | --- |
| Low: Top 30%-50% of school | 2,545 |
| High: Top 10% of school | 2,473 |
| Average: Top 10%-30% of school | 2,416 |
| Poor: Bottom 50% of school | 2,336 |
| High: Academic performance ranked in the top 10% of the school. | 49 |
| Mid: Ranked 10% to 30% in the school based on academic performance. | 48 |
| Low: Academic performance ranked in the top 30% to 50% of the school. | 40 |
| Poor: Academic performance ranks in the bottom 50% of the school. | 29 |

CN `学术水平` 4종만: 低 2,592 / 高 2,536 / 中 2,486 / 差 2,386.

### Grade 5·6 × 수준 교차표 (EN, 학년 정규화 기준; 중국어 라벨 1건 제외)

| 학년 | High | Average | Mid | Low | Poor | 합계 |
| --- | --- | --- | --- | --- | --- | --- |
| 5 | 214 | 205 | 6 | 220 | 175 | 820 |
| 6 | 197 | 197 | 2 | 350 | 203 | 949 |

CN 교차표: 5학년 高 215 / 中 214 / 低 219 / 差 176 (824), 6학년 高 197 / 中 200 / 低 350 / 差 202 (949).

학년 필터 후 4범주 균등 추출(세션당 2~6명)에 필요한 표본은 범주당 최소 175건 이상으로 확보된다. `Mid`를 `Average`와 합치는 정규화가 필요하다.

## 6. 다운로드 방법

- 인증 불필요: `curl -L https://huggingface.co/datasets/sii-research/HACHIMI-1M/resolve/main/merged_students_10k_EN.jsonl` 로 HTTP 200, 74,252,201 B 수신 확인(2026-10-21).
- `huggingface_hub` 없이 가능. 이 저장소에는 `huggingface_hub`/`datasets`가 설치되어 있지 않고 `requirements*.txt`에도 없다(`python3 -c "import huggingface_hub"` → ModuleNotFoundError).
- 저장소 커밋 가능성: EN 70.8 MiB, CN 49.0 MiB. GitHub 권장 50 MB 경고 한계를 EN이 넘고(경고, 차단은 100 MB), 현재 `.gitignore`는 `data/*.db`만 제외한다. `data/` 디렉터리는 현재 저장소에 없다. 이 문서는 사실만 기록하며 커밋 여부는 결정 사항이다.

## 7. 레코드 예시 1건 (EN, id 1, 서술 필드는 160자에서 절단)

```json
{
  "id": 1,
  "age": 13,
  "gender": "female",
  "grade": "Grade 7 (Junior High)",
  "development_stage": {
    "piaget_cognitive_stage": "Formal Operational Stage",
    "erikson_psychosocial_stage": "Identity vs. Role Confusion",
    "kohlberg_moral_stage": "Conventional Level"
  },
  "strong_subjects": ["Art"],
  "weak_subjects": ["Mathematics", "English", "Physics"],
  "academic_level": "Poor: Bottom 50% of school",
  "personality": "Student No. 1 has an introverted personality and enjoys sharing her art creations with familiar classmates, expressing emotions in a delicate manner. However, s ...",
  "values": "In terms of moral cultivation, she respects her classmates and occasionally helps friends around her, generally placing her at an average level; her physical an ...",
  "social_relationships": "Student No. 1 has a relatively peaceful relationship with her classmates during her first year of junior high school. She often exchanges her artwork with a few ...",
  "creativity": "The fluency is moderate, as the student can express personal themes relatively smoothly while drawing; the originality is high, with the ability to incorporate  ...",
  "mental_health": "Student 1 exhibits an overall psychological state that leans towards sensitivity, with a habit of self-observation, particularly showing significant emotional f ...",
  "sampling_constraints": {
    "grade": "Grade 7 (Junior High)",
    "gender": "female",
    "strength_subject_bias": ["Art", "Music", "Physical Education"],
    "target_academic_level": "Poor: Bottom 50% of school"
  }
}
```

초등 6학년 예시 머리 부분(id 8): `age 12, gender male, grade "Grade 6 (Primary)", piaget "Formal Operational Stage", erikson "Industry vs. Inferiority", kohlberg "Conventional Level", strong_subjects ["Chinese Language","Geography","Mathematics"], weak_subjects ["Biology","English","Art"], academic_level "Average: Top 10%-30% of school"`.

## 8. 미확인

- 중복 id 33쌍(62~94)이 생긴 원인, 누락 id 97개의 원인: 미확인(카드·커밋 메시지에 설명 없음. 커밋 이력상 두 파일은 2026-01-13부터 2026-03-27까지 여러 번 삭제·재업로드됨).
- README의 "10,000 records" 와 EN 9,936행의 차이에 대한 저자 설명: 미확인.
- 전체 1M 공개 시점과 라이선스: 미확인.
