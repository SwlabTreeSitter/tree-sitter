# Scripts

이 디렉토리의 Python / Shell 스크립트 17개의 역할 목록.
파이프라인을 처음 보는 사람은 [실험 재현 워크플로우](#실험-재현-워크플로우) 부터 보는 게 빠름.

## Quick reference (4 카테고리)

| 카테고리 | 개수 | 진입점 / 핵심 |
|---|---|---|
| [1. 오케스트레이터](#1-오케스트레이터-shell-4개) | 4 (sh) | `run_pipeline_all.sh` |
| [2. 파이프라인 코어](#2-파이프라인-코어-python-5개) | 5 (py) | `evaluate_coverage.py` |
| [3. 리포트 / 집계](#3-리포트--집계-python-3개) | 3 (py) | `rq1_three_metrics.py` |
| [4. 통계 / 시각화](#4-통계--시각화-3개) | 3 (py + sh) | `plot_rank_distribution.py` |


---

## 1. 오케스트레이터 (Shell, 4개)

파이프라인을 *"어떻게 돌리는지"* 의 진입점. 사용자가 직접 호출.

| 파일 | 역할 |
|---|---|
| `run_pipeline_all.sh` | 모든 언어 병렬 실행. `--build-only`, `--skip-collect`, `--learn-only` 등 옵션 |
| `run_pipeline.sh` | 단일 언어 4단계 파이프라인 (LEARN → TEST → answers → evaluate) |
| `rebuild_all.sh` | 단일 언어 빌드 + LEARN 컬렉션 (run_pipeline.sh Step 1 내부에서 호출) |
| `rebuild_ts_and_exe.sh` | tree-sitter 코어 + TreeSitterCutFile.exe 만 (언어 무관) |

**호출 관계**:
```
run_pipeline_all.sh
  └─ run_pipeline.sh <lang>
       ├─ rebuild_all.sh <lang>           (Step 1)
       │    ├─ rebuild_ts_and_exe.sh
       │    ├─ tree-sitter generate / build
       │    ├─ to_data_batch_collect_learn.py
       │    ├─ to_json_aggregate.py
       │    └─ npx node-gyp rebuild       (VSCode addon)
       │
       ├─ to_data_batch_collect_test.py   (Step 2)
       ├─ to_json_per_file_test.py        (Step 3)
       └─ evaluate_coverage.py            (Step 4)
```

---

## 2. 파이프라인 코어 (Python, 5개)

`run_pipeline.sh` 가 순차 호출하는 핵심

| 파일 | 단계 | 역할 |
|---|---|---|
| `to_data_batch_collect_learn.py` | Step 1 | LEARN 세트 → TreeSitterCutFile mode 3 → Test.data 들 |
| `to_json_aggregate.py` | Step 1 | Test.data 들 → `candidates.json` (state→후보 DB) |
| `to_data_batch_collect_test.py` | Step 2 | TEST 세트 → TreeSitterCutFile mode 1 → 평가 입력 |
| `to_json_per_file_test.py` | Step 3 | TEST 데이터 → 정답지 JSON (커서별 정답) |
| `evaluate_coverage.py` | Step 4 | 정답지 + candidates.json → 랭크 + 커버리지 측정. CSV 산출 |

**데이터 흐름**:
```
[LEARN 세트]                                      [TEST 세트]
    │                                                  │
    ▼ to_data_batch_collect_learn (mode 3)             ▼ to_data_batch_collect_test (mode 1)
[Test.data 파일들 (LEARN)]                        [Test.data 파일들 (TEST)]
    │                                                  │
    ▼ to_json_aggregate                                ▼ to_json_per_file_test
[candidates.json (DB)]                            [정답지 JSON]
    │                                                  │
    └────────────────────┬─────────────────────────────┘
                         ▼ evaluate_coverage
            reports/<lang>/<lang>_file_performance.csv     (파일별 + Top-K)
            reports/<lang>/debug_coverage_<lang>/*.csv     (per-file 상세)
```

**평가 결과 카테고리** (evaluate_coverage.py 가 분류하는 라벨):
- `FOUND` — 정답이 후보 목록에 있음 (rank 무관). Top-1/3/5/10/20 은 별도 통계
- `NOT_FOUND` — 정답이 후보 목록에 없음 (rank == 0)
- `FAIL` — conversion 자체가 빈 결과 반환

---

## 3. 리포트 / 집계 (Python, 3개)

`run_pipeline.sh` 가 자동 호출하지 않음. **사용자가 별도 실행**

| 파일 | 역할 |
|---|---|
| `rq1_three_metrics.py` | RQ1 의 세 지표 산출 |
| `generate_project_performance.py` | 전체 언어 - 프로젝트별 성능 및 loc 리포트 |
| `run_evaluate_projects.py` | 특정 프로젝트만 파이프라인 재실행 |

---

## 4. 통계 / 시각화 (3개)

| 파일 | 역할 |
|---|---|
| `plot_rank_distribution.py` | 랭크 분포 시각화 (matplotlib) |
| `loc_summary.py` | LOC 요약 통계 |
| `count_loc.sh` | LOC 카운팅 (셸) |

---

## 외부 (`code-completion-extension/`)

VS Code extension repo 안 (별도 저장소):

| 파일 | 역할 |
|---|---|
| `code-completion-extension/native/generate_build_config.py` | binding.gyp + addon.cc 의 언어별 블록 생성 (node-gyp 빌드 사전준비) |

`rebuild_all.sh` 의 Step 6 에서 호출됨.

---

## 실험 재현 워크플로우

### 기본 실행 순서

```bash
# 1. 평가 파이프라인 실행 (9개 언어)
./run_pipeline_all.sh

# 2. 리포트 / 집계
python3 rq1_three_metrics.py              # 평가 결과 → 논문 지표
python3 generate_project_performance.py   # 전체 언어 - 프로젝트별 성능 및 loc 리포트
```

### 옵션 / 부분 실행

빌드만 검증:
```bash
./run_pipeline_all.sh --build-only
```

특정 단계 skip (시간 절약):
```bash
./run_pipeline_all.sh --skip-collect       # 컬렉션 skip, 평가만 재실행
./run_pipeline.sh haskell --learn-only     # 단일 언어 LEARN 만
./run_pipeline.sh c --skip-test-collect    # 단일 언어 TEST 컬렉션 skip
```

코어 빌드만 (parser.c 등 수정 후):
```bash
./rebuild_ts_and_exe.sh
```

특정 프로젝트만 재평가:
```bash
python3 run_evaluate_projects.py haskell LPFP
```

## 산출물 위치

```
tree-sitter/
├── reports/
│   ├── <lang>/
│   │   ├── <lang>_file_performance.csv               (Step 4 핵심 결과 — 언어 전체)
│   │   ├── <lang>_file_performance_<project>.csv     (프로젝트별, evaluate_coverage 가 같이 출력)
│   │   └── debug_coverage_<lang>/*.csv               (per-file 상세)
│   └── (전역 집계 CSV 들, 리포트 단계 산출물)
├── pipeline_summary_<lang>.log               (각 언어 실행 요약)
└── codecompletion_benchmarks/<lang>/         (입력 코퍼스, 별도)
    ├── LEARN/
    └── TEST/
```

## 주의사항

- 다른 환경 이전 시 hardcoded 경로 갱신 필요:
  - 파이프라인 코어 (`to_data_*`, `to_json_*`): 파일 상단 `ROOT = "/home/hyeonjin/PL"`
  - `evaluate_coverage.py` + 리포트 스크립트: `LANG_CONFIGS` dict 안의 언어별 경로
- 산출물 파일은 매 실행 시 덮어써짐
