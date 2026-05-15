# tree-sitter fork — code completion 연구

> 본 저장소는 [tree-sitter](https://tree-sitter.github.io) 의 fork 로, *parse_state 기반 코드 자동완성 DB* 와 *커서 시점 state 변환* 을 위한 커스텀 기능이 추가됨.  
> 예전 tree-sitter README 는 [README.legacy.md](README.legacy.md).
> 
> 2026.05.15 update / contatct: wisetreasurelee@gmail.com

---

## 1. 프로젝트 개요

**핵심 아이디어**: *parse_state → 구조후보 DB* + *커서 위치 → state 변환* + *LLM 통합* 으로 코드 자동완성.

[선행 연구](https://dl.acm.org/doi/epdf/10.1145/3605098.3635944) (smallbasic, C 두 언어) 에서:
- Top-3 구조후보 + LLM 텍스트 후보가 *사용자 기대 완성에 가깝다* 는 결론.

본 연구는 이 결론이 **주요 프로그래밍 언어** 로 확장돼도 유효한지 검증:
- smallbasic, C, C++, Java, JavaScript, Python, Ruby, PHP, Haskell

---

## 2. 연구 흐름 — 4 단계

```
[Stage 1] DB 구축 (학습)
   LEARN 세트 → 파싱 → 구조후보 추출 → 빈도 정렬 → candidates.json
        └─ 알고리즘:    COLLECTION.md
        └─ 파이프라인:  SCRIPTS.md

[Stage 2] VS Code 자동완성 (추론)
   커서 위치 → state 합집합 → DB lookup → LLM 프롬프트 → 텍스트 후보
        └─ 커서→state 알고리즘: CONVERSION.md
        └─ VS Code extension: code-completion-extension/README.md

[Stage 3] 구조후보 정확도 평가 (RQ1)
   TEST 세트 → 토큰별 state 추출 → DB lookup → Top-K 일치율
        └─ 평가 파이프라인: SCRIPTS.md (Step 2~4)

[Stage 4] 텍스트 후보 정확도 (With/Without LLM)
   LLM 프롬프트에 구조후보 포함 vs 미포함 → 텍스트 정확도 비교
```

---

## 3. 문서 지도

| 문서 | 내용 | 언제 보나 |
|---|---|---|
| **[SCRIPTS.md](SCRIPTS.md)** | 파이프라인 (LEARN/TEST/평가) 의 스크립트 구성 + 실행 순서 | *돌리고 싶을 때* — 어떤 명령 어떤 순서로 |
| **[COLLECTION.md](COLLECTION.md)** | 구조후보 DB 빌드 알고리즘 (`parser.c` 의 `collect_recursive`) | *DB 가 어떻게 만들어지는가* |
| **[CONVERSION.md](CONVERSION.md)** | 커서 → parse_state 합집합 알고리즘 (`parser.c` 의 `parse_for_conversion`) | *VS Code 자동완성의 진입 단계* |
| **`code-completion-extension/README.md`** | VS Code extension 사용법 + LLM 통합 | *extension 개발/디버깅* |
| [README.legacy.md](README.legacy.md) | tree-sitter 예전 README | *tree-sitter 초기 노트* |

---

## 4. Getting Started


1. **이 README** 로 큰 그림 확보 ← *지금 보고 있는 문서*
2. **[SCRIPTS.md](SCRIPTS.md)** 의 *실험 재현 워크플로우* 로 파이프라인 한 번 실행
3. 알고리즘 깊이가 필요하면:
   - DB 빌드 → **[COLLECTION.md](COLLECTION.md)**
   - VS Code 자동완성 → **[CONVERSION.md](CONVERSION.md)**
4. VS Code 통합 → **`code-completion-extension/README.md`**

혹은 역으로 
1. **`code-completion-extension/README.md`** 부터 시스템 동작 파악 후
2. **이 README**로 실험 재현 / 세부적인 트리시터 내용 접근

빠른 실행 예 (모든 언어 파이프라인):
```bash
./run_pipeline_all.sh
```

자세한 옵션 (특정 언어만, 빌드만, skip 등): [SCRIPTS.md](SCRIPTS.md)

---

## 5. 디렉토리 구조

```
tree-sitter/
├── README.md                       ← 이 문서 (프로젝트 entry point)
├── README.legacy.md                ← tree-sitter 본 README + 초기 노트
├── SCRIPTS.md                      ← 파이프라인 스크립트 가이드
├── COLLECTION.md                   ← DB 빌드 알고리즘
├── CONVERSION.md                   ← 커서 → state 알고리즘
│
├── lib/                            ← tree-sitter 코어 (fork 된 parser.c, stack.c 포함)
├── tree-sitter-<lang>/             ← 각 언어 grammar (smallbasic, c, cpp, java, ...)
├── codecompletion_benchmarks/      ← LEARN/TEST 세트 (각 언어별)
├── code-completion-extension/      ← VS Code extension (별도 repo, sibling)
│
├── reports/                        ← 평가 결과 CSV/MD
├── images/                         ← doc 첨부 이미지
│
├── TreeSitterCutFile.cpp           ← C++ 실행파일 (collection/conversion 모드)
├── to_data_batch_collect_*.py      ← LEARN/TEST 데이터 생성
├── to_json_aggregate.py            ← DB 집계
├── evaluate_coverage.py            ← Stage 3 평가
└── run_pipeline_all.sh             ← 전체 파이프라인 진입점
```

---

## 6. tree-sitter fork 의 주요 customization

원본 tree-sitter 대비 *추가된 기능* 요약:

- **`parser.c`** 에:
  - *Collection mode* — `collect_recursive` 가 트리 순회로 (state, 구조후보) 추출
  - *Conversion mode* — 커서 시점 state 합집합 추출
- **`stack.c`** 에:
  - `ts_stack_simulate_conversion`
- **`api.h`** 의 `Custom` 블록 — 위 기능들의 공개 API

자세한 알고리즘은 [COLLECTION.md](COLLECTION.md), [CONVERSION.md](CONVERSION.md).

---

## 7. Todo List

- 컨버전 알고리즘 검증: 보완 로직이 적절한지
  - vs code extension에서 직접 커서 위치마다 실행해보며 디버깅하는 방법: ![README-부록](https://github.com/chaendaya/code-completion-extension/tree/main)

- Top-10 구조후보 정확도 실험 9개 언어로 재연 및 결과 분석

- Top-3 구조후보 + LLM 텍스트 후보 실험 9개 언어로 재연 및 결과 분석
