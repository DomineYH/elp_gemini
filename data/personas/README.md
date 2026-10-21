# 페르소나 데이터: HACHIMI-1M Grade 5·6 축소 표본

`hachimi_grade5_6_en.jsonl`은 수업 시뮬레이션의 후보 페르소나 원천이다 (ADR 0002). 앱은 런타임에 네트워크를 쓰지 않고 이 파일만 읽는다.

## 출처

- 데이터셋: [sii-research/HACHIMI-1M](https://huggingface.co/datasets/sii-research/HACHIMI-1M) (Hugging Face)
- 원본 파일: `merged_students_10k_EN.jsonl` (저장소 루트, 74,252,201 B, 9,936행)
- HF revision: `ff2ae731d7202f3f4ab483452dc85763ada5d321`
- 원본 sha256: `c6aedd3fdf4ded00ae36fa81ca5767f6e6b1375bd54aad202eb597bbe16efa58`
- 생성 파일 sha256: `890fae866d291698ea4473955b974363615a8d0fb5d96f2836602ef0a6b9efb3`
- 성격: 합성 데이터 (모든 페르소나는 Qwen2.5-72B로 생성, 실명 제거). 실제 학생이 아니다.
- 데이터셋 카드 요청: 차별적 평가나 해로운 목적에 쓰지 않는다 ("Do not use data for discriminatory assessment or harmful purposes").

## 변환 규칙 (`scripts/load_personas.py`)

- `grade`에서 학년 번호를 읽어 5·6학년만 남긴다 (`Grade 5 (Primary)`, `English: Grade 6 …`, `Fifth grade`, `Sixth grade`). 정수로 저장.
- `academic_level` `"<범주>: <설명>"`을 `academic_level`(High/Average/Low/Poor, `Mid`→`Average`)과 `academic_level_desc`로 나눈다.
- `sampling_constraints`는 버린다.
- 중복 id는 파일 순서상 첫 행만 남기고, id 오름차순으로 저장한다.
- 키 순서: id, age, gender, grade, academic_level, academic_level_desc, development_stage, strong_subjects, weak_subjects, personality, values, social_relationships, creativity, mental_health.

## 행 수

총 **1,761**행 (중복 id 8건 제거 후).

| 학년 | High | Average | Low | Poor | 합계 |
| --- | --- | --- | --- | --- | --- |
| 5 | 212 | 210 | 218 | 175 | 815 |
| 6 | 196 | 199 | 349 | 202 | 946 |

## 다시 만들기

```bash
curl -L -o merged_students_10k_EN.jsonl \
  https://huggingface.co/datasets/sii-research/HACHIMI-1M/resolve/ff2ae731d7202f3f4ab483452dc85763ada5d321/merged_students_10k_EN.jsonl
sha256sum merged_students_10k_EN.jsonl   # c6aedd3f…a58 확인
python scripts/load_personas.py merged_students_10k_EN.jsonl
```

학년을 넓히려면 스크립트의 `KEEP_GRADES`를 바꿔 다시 생성하고 이 README의 sha256·행 수를 갱신해 커밋한다.

## 인용

```bibtex
@article{jiang2026hachimi,
  title={HACHIMI: Scalable and Controllable Student Persona Generation via Orchestrated Agents},
  author={Jiang, Yilin and Tan, Fei and Yin, Xuanyu and Leng, Jing and Zhou, Aimin},
  journal={arXiv preprint arXiv:2603.04855},
  year={2026}
}
```

## 라이선스 (MIT)

```
MIT License

Copyright (c) 2025 HACHIMI Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
