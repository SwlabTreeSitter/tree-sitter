#!/bin/bash

# =============================================================
# run_pipeline_all.sh
# 모든 언어에 대해 병렬로 run_pipeline.sh를 실행한다.
# 각 언어의 summary는 pipeline_summary_<lang>.log에 기록된다.
#
# 사용법:
#   ./run_pipeline_all.sh [옵션] [언어1 언어2 ...]
#   ./run_pipeline_all.sh                                   # 기본: 전체 언어 실행
#   ./run_pipeline_all.sh --skip-collect                    # 전체 컬렉션 스킵 (정답지+평가만)
#   ./run_pipeline_all.sh --skip-learn-collect              # LEARN 컬렉션 스킵 (TEST 재수집+평가)
#   ./run_pipeline_all.sh --skip-test-collect               # TEST 컬렉션 스킵 (LEARN 재수집+평가)
#   ./run_pipeline_all.sh --per-project haskell             # 하스켈만, 프로젝트별 집계 포함
#   ./run_pipeline_all.sh --skip-learn-collect ruby python  # LEARN 스킵, ruby+python만
#
# 옵션:
#   --skip-collect         Step 1(LEARN) + Step 2(TEST) 컬렉션 모두 건너뜀
#   --skip-learn-collect   Step 1(LEARN 컬렉션) 만 건너뜀
#   --skip-test-collect    Step 2(TEST 컬렉션) 만 건너뜀
#   --per-project          Step 4 완료 후 프로젝트별 결과도 집계하여 출력/저장
# =============================================================

TS_DIR="$(cd "$(dirname "$0")" && pwd)"

# 기본 실행 언어 목록 (실행 순서)
ALL_LANGUAGES=(smallbasic c haskell ruby php javascript cpp java python)

# 인자 파싱: 플래그 분리
SKIP_COLLECT_FLAG=""
SKIP_LEARN_COLLECT_FLAG=""
SKIP_TEST_COLLECT_FLAG=""
PER_PROJECT_FLAG=""
BUILD_ONLY=false
LANG_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --skip-collect)       SKIP_COLLECT_FLAG="--skip-collect" ;;
        --skip-learn-collect) SKIP_LEARN_COLLECT_FLAG="--skip-learn-collect" ;;
        --skip-test-collect)  SKIP_TEST_COLLECT_FLAG="--skip-test-collect" ;;
        --per-project)        PER_PROJECT_FLAG="--per-project" ;;
        --build-only)         BUILD_ONLY=true ;;
        *)                    LANG_ARGS+=("$arg") ;;
    esac
done

# 언어 목록 결정
if [ ${#LANG_ARGS[@]} -gt 0 ]; then
    LANGUAGES=("${LANG_ARGS[@]}")
else
    LANGUAGES=("${ALL_LANGUAGES[@]}")
fi

# 파이프라인 실패 시 개별 언어를 건너뛰고 계속 진행
set +e

# =================[ 로그 헤더 ]=================
echo "############################################################"
echo "  run_pipeline_all.sh"
echo "  Start   : $(date '+%Y-%m-%d %H:%M:%S')"
echo "  Languages: ${LANGUAGES[*]}"
_OPT_STR="${SKIP_COLLECT_FLAG:+$SKIP_COLLECT_FLAG }${SKIP_LEARN_COLLECT_FLAG:+$SKIP_LEARN_COLLECT_FLAG }${SKIP_TEST_COLLECT_FLAG:+$SKIP_TEST_COLLECT_FLAG }${PER_PROJECT_FLAG}"
echo "  Options : ${_OPT_STR:-none}"
echo "############################################################"
echo ""

TOTAL_START=$(date +%s)
FAILED=()
SUCCEEDED=()

# =================[ 빌드 (병렬 실행 전 1회) ]=================
echo "  [ALL] Building TreeSitterCutFile.exe + VSCode addon..."
bash "$TS_DIR/rebuild_ts_and_exe.sh" 2>&1
if [ -d "$TS_DIR/../code-completion-extension" ]; then
    cd "$TS_DIR/../code-completion-extension"
    if [ -f package-lock.json ]; then npm ci --silent 2>&1; else npm install --silent 2>&1; fi
    python3 generate_build_config.py 2>&1
    npx node-gyp rebuild 2>&1
    echo "  [ALL] VSCode addon rebuild done."
    cd "$TS_DIR"
fi
echo ""

if [ "$BUILD_ONLY" = true ]; then
    echo "  [ALL] --build-only: build finished, skipping evaluation."
    exit 0
fi

# =================[ 언어별 실행 (병렬) ]=================
PIDS=()

for LANG in "${LANGUAGES[@]}"; do
    LANG_LOG="$TS_DIR/pipeline_summary_${LANG}.log"
    # 이어쓰기 (append)

    (
        LANG_START=$(date +%s)

        # run_pipeline.sh의 SUMMARY_LOG를 언어별 파일로 지정
        export PIPELINE_SUMMARY_LOG="$LANG_LOG"

        bash "$TS_DIR/run_pipeline.sh" "$LANG" $SKIP_COLLECT_FLAG $SKIP_LEARN_COLLECT_FLAG $SKIP_TEST_COLLECT_FLAG $PER_PROJECT_FLAG > /dev/null 2>&1
        EXIT_CODE=$?

        LANG_ELAPSED=$(( $(date +%s) - LANG_START ))

        exit $EXIT_CODE
    ) &
    PIDS+=($!)
    echo "  [ALL] Started $LANG (PID=$!)"
done

# 모든 프로세스 완료 대기
echo ""
echo "  [ALL] Waiting for ${#PIDS[@]} languages to finish..."

for i in "${!PIDS[@]}"; do
    LANG="${LANGUAGES[$i]}"
    PID="${PIDS[$i]}"
    if wait "$PID"; then
        SUCCEEDED+=("$LANG")
        echo "  [ALL] $LANG finished (success)"
    else
        FAILED+=("$LANG")
        echo "  [ALL] $LANG finished (FAILED)"
    fi
done

# =================[ 요약 ]=================
TOTAL_ELAPSED=$(( $(date +%s) - TOTAL_START ))
echo ""
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
echo "  [ALL] Summary logs: pipeline_summary_<lang>.log"
echo "############################################################"

# 실패한 언어가 있으면 non-zero 반환
[ ${#FAILED[@]} -eq 0 ]
