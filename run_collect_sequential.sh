#!/bin/bash

# =============================================================
# run_collect_sequential.sh
# Step 1(LEARN 컬렉션) + Step 2(TEST 컬렉션)만 순차 실행한다.
# rebuild_all.sh가 공유 파일(.o, .exe)을 쓰므로 병렬 실행 불가.
#
# 이후 run_pipeline_all.sh --skip-collect 로 평가를 병렬 실행한다.
#
# 사용법:
#   ./run_collect_sequential.sh                          # 전체 언어
#   ./run_collect_sequential.sh ruby python              # 특정 언어만
#   ./run_collect_sequential.sh --skip-learn-collect      # LEARN 스킵 (TEST만)
#   ./run_collect_sequential.sh --skip-test-collect       # TEST 스킵 (LEARN만)
# =============================================================

set -e
set -o pipefail

TS_DIR="$(cd "$(dirname "$0")" && pwd)"

ALL_LANGUAGES=(smallbasic c haskell ruby php javascript cpp java python)

# 인자 파싱
SKIP_LEARN_COLLECT=false
SKIP_TEST_COLLECT=false
LANG_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --skip-learn-collect) SKIP_LEARN_COLLECT=true ;;
        --skip-test-collect)  SKIP_TEST_COLLECT=true ;;
        --skip-collect)       SKIP_LEARN_COLLECT=true; SKIP_TEST_COLLECT=true ;;
        *)                    LANG_ARGS+=("$arg") ;;
    esac
done

if [ ${#LANG_ARGS[@]} -gt 0 ]; then
    LANGUAGES=("${LANG_ARGS[@]}")
else
    LANGUAGES=("${ALL_LANGUAGES[@]}")
fi

TOTAL_START=$(date +%s)

echo "============================================================"
echo "  run_collect_sequential.sh"
echo "  Start    : $(date '+%Y-%m-%d %H:%M:%S')"
echo "  Languages: ${LANGUAGES[*]}"
echo "  Skip LEARN: $SKIP_LEARN_COLLECT"
echo "  Skip TEST : $SKIP_TEST_COLLECT"
echo "============================================================"
echo ""

REBUILD_SCRIPT="$TS_DIR/rebuild_all.sh"
COLLECT_TEST="$TS_DIR/to_data_batch_collect_test.py"

FAILED=()
SUCCEEDED=()

for LANG in "${LANGUAGES[@]}"; do
    echo "============================================================"
    echo "  >>> $LANG"
    echo "============================================================"

    LANG_START=$(date +%s)
    LANG_OK=true

    # Step 1: LEARN 컬렉션
    if [ "$SKIP_LEARN_COLLECT" = true ]; then
        echo "  [Step 1] LEARN collection  [SKIPPED]"
    else
        echo "  [Step 1] LEARN collection"
        if ! bash "$REBUILD_SCRIPT" "$LANG" 2>&1; then
            echo "  [Step 1] FAILED"
            LANG_OK=false
        fi
    fi

    # Step 2: TEST 컬렉션
    if [ "$SKIP_TEST_COLLECT" = true ]; then
        echo "  [Step 2] TEST collection  [SKIPPED]"
    elif [ "$LANG_OK" = true ]; then
        echo "  [Step 2] TEST collection"
        if ! cd "$TS_DIR" && python3 "$COLLECT_TEST" "$LANG" 2>&1; then
            echo "  [Step 2] FAILED"
            LANG_OK=false
        fi
    fi

    LANG_ELAPSED=$(( $(date +%s) - LANG_START ))

    if [ "$LANG_OK" = true ]; then
        SUCCEEDED+=("$LANG")
        echo "  <<< DONE: $LANG (${LANG_ELAPSED}s)"
    else
        FAILED+=("$LANG")
        echo "  <<< FAILED: $LANG (${LANG_ELAPSED}s)"
    fi
    echo ""
done

TOTAL_ELAPSED=$(( $(date +%s) - TOTAL_START ))
echo "============================================================"
echo "  Finished (${TOTAL_ELAPSED}s)"
if [ ${#SUCCEEDED[@]} -gt 0 ]; then
    echo "  Succeeded: ${SUCCEEDED[*]}"
fi
if [ ${#FAILED[@]} -gt 0 ]; then
    echo "  Failed: ${FAILED[*]}"
fi
echo ""
echo "  다음 단계: ./run_pipeline_all.sh --skip-collect"
echo "============================================================"

[ ${#FAILED[@]} -eq 0 ]
