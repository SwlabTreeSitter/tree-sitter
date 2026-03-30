#!/bin/bash

# =============================================================
# run_pipeline_all.sh
# 모든 언어에 대해 순차적으로 run_pipeline.sh를 실행한다.
# 각 Python 스크립트(to_data_batch_collect_learn_*, _test_*,
# to_json_aggregate_*, to_json_per_file_test_*, evaluate_struct_*,
# evaluate_coverage)의 출력을 단일 로그 파일에 언어별로 기록한다.
#
# 사용법:
#   ./run_pipeline_all.sh [--skip-collect] [--per-project] [언어1 언어2 ...]
#   ./run_pipeline_all.sh                             # 기본: 전체 언어 실행
#   ./run_pipeline_all.sh --skip-collect              # 전체 언어, 컬렉션 스킵
#   ./run_pipeline_all.sh --per-project haskell       # 하스켈만, 프로젝트별 집계 포함
#   ./run_pipeline_all.sh --skip-collect --per-project haskell python
#
# 옵션:
#   --skip-collect   각 언어의 Step 1(rebuild) + Step 2(collect TEST) 를 건너뜀
#   --per-project    Step 4 완료 후 프로젝트별 결과도 집계하여 출력/저장
#
# 로그 파일: pipeline_all_YYYYMMDD_HHMMSS.log
# =============================================================

TS_DIR="$(cd "$(dirname "$0")" && pwd)"

# 기본 실행 언어 목록 (실행 순서)
ALL_LANGUAGES=(smallbasic c11 haskell ruby php javascript cpp java python)

# 인자 파싱: 플래그 분리
SKIP_COLLECT_FLAG=""
PER_PROJECT_FLAG=""
LANG_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --skip-collect) SKIP_COLLECT_FLAG="--skip-collect" ;;
        --per-project)  PER_PROJECT_FLAG="--per-project" ;;
        *)              LANG_ARGS+=("$arg") ;;
    esac
done

# 언어 목록 결정
if [ ${#LANG_ARGS[@]} -gt 0 ]; then
    LANGUAGES=("${LANG_ARGS[@]}")
else
    LANGUAGES=("${ALL_LANGUAGES[@]}")
fi

# 로그 파일 경로 (타임스탬프 포함)
LOG_FILE="$TS_DIR/pipeline_all_$(date '+%Y%m%d_%H%M%S').log"

# 파이프라인 실패 시 개별 언어를 건너뛰고 계속 진행
set +e

# pipefail: tee 앞 명령의 종료 코드를 올바르게 받기 위해 활성화
set -o pipefail

# =================[ 로그 헤더 ]=================
{
    echo "############################################################"
    echo "  run_pipeline_all.sh"
    echo "  Start   : $(date '+%Y-%m-%d %H:%M:%S')"
    echo "  Languages: ${LANGUAGES[*]}"
    _OPT_STR="${SKIP_COLLECT_FLAG:+$SKIP_COLLECT_FLAG }${PER_PROJECT_FLAG}"
    echo "  Options : ${_OPT_STR:-none}"
    echo "  Log file: $LOG_FILE"
    echo "############################################################"
    echo ""
} | tee "$LOG_FILE"

TOTAL_START=$(date +%s)
FAILED=()
SUCCEEDED=()

# =================[ 언어별 실행 ]=================
for LANG in "${LANGUAGES[@]}"; do
    {
        echo "============================================================"
        echo "  [ALL] >>> Language: $LANG"
        echo "  [ALL]     Start   : $(date '+%Y-%m-%d %H:%M:%S')"
        echo "============================================================"
    } | tee -a "$LOG_FILE"

    LANG_START=$(date +%s)

    # run_pipeline.sh 실행; stdout+stderr → 터미널(tee) + 로그 파일(append)
    bash "$TS_DIR/run_pipeline.sh" "$LANG" $SKIP_COLLECT_FLAG $PER_PROJECT_FLAG 2>&1 | tee -a "$LOG_FILE"
    EXIT_CODE=${PIPESTATUS[0]}

    LANG_ELAPSED=$(( $(date +%s) - LANG_START ))

    if [ "$EXIT_CODE" -eq 0 ]; then
        SUCCEEDED+=("$LANG")
        {
            echo ""
            echo "  [ALL] <<< DONE   : $LANG  (${LANG_ELAPSED}s)"
        } | tee -a "$LOG_FILE"
    else
        FAILED+=("$LANG")
        {
            echo ""
            echo "  [ALL] <<< FAILED : $LANG  (exit=$EXIT_CODE, ${LANG_ELAPSED}s)"
        } | tee -a "$LOG_FILE"
    fi

    echo "" | tee -a "$LOG_FILE"
done

# =================[ 요약 ]=================
TOTAL_ELAPSED=$(( $(date +%s) - TOTAL_START ))
{
    echo "############################################################"
    echo "  [ALL] Pipeline finished"
    echo "  [ALL] End    : $(date '+%Y-%m-%d %H:%M:%S')"
    echo "  [ALL] Elapsed: ${TOTAL_ELAPSED}s"
    echo ""
    if [ ${#SUCCEEDED[@]} -gt 0 ]; then
        echo "  [ALL] Succeeded (${#SUCCEEDED[@]}): ${SUCCEEDED[*]}"
    fi
    if [ ${#FAILED[@]} -gt 0 ]; then
        echo "  [ALL] Failed    (${#FAILED[@]}): ${FAILED[*]}"
    else
        echo "  [ALL] All languages completed successfully."
    fi
    echo "  [ALL] Log file : $LOG_FILE"
    echo "############################################################"
} | tee -a "$LOG_FILE"

# 실패한 언어가 있으면 non-zero 반환
[ ${#FAILED[@]} -eq 0 ]
