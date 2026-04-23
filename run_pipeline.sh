#!/bin/bash

# =============================================================
# run_pipeline.sh
# 언어명을 인자로 받아 rebuild_all → 랭크+커버리지 평가까지 전체 파이프라인 실행
#
# 사용법:
#   ./run_pipeline.sh <언어> [옵션]
#
# 옵션:
#   --skip-learn-collect   Step 1(LEARN 컬렉션) 만 건너뜀
#   --skip-test-collect    Step 2(TEST 컬렉션) 만 건너뜀
#   --skip-collect         Step 1 + Step 2 모두 건너뜀 (위 두 옵션의 조합)
#   --per-project          Step 4 평가 완료 후 프로젝트별 결과도 집계하여 출력
#
# 지원 언어:
#   smallbasic   sb
#   c
#   haskell
#   ruby
#   php
#   javascript   js
#   cpp
#   java
#   python
# =============================================================

set -e
set -o pipefail

TS_DIR="$(cd "$(dirname "$0")" && pwd)"

# =================[ 인자 파싱 ]=================
SKIP_LEARN_COLLECT=false
SKIP_TEST_COLLECT=false
PER_PROJECT=false
LEARN_ONLY=false

_POSITIONAL=()
for arg in "$@"; do
    case "$arg" in
        --skip-collect)       SKIP_LEARN_COLLECT=true; SKIP_TEST_COLLECT=true ;;
        --skip-learn-collect) SKIP_LEARN_COLLECT=true ;;
        --skip-test-collect)  SKIP_TEST_COLLECT=true ;;
        --per-project)        PER_PROJECT=true ;;
        --learn-only)         LEARN_ONLY=true ;;
        *)                    _POSITIONAL+=("$arg") ;;
    esac
done
set -- "${_POSITIONAL[@]}"

if [ $# -ne 1 ]; then
    echo "Usage: $0 <language> [--skip-collect]"
    echo ""
    echo "  Supported languages:"
    echo "    smallbasic  (alias: sb)"
    echo "    c"
    echo "    haskell"
    echo "    ruby"
    echo "    php"
    echo "    javascript  (alias: js)"
    echo "    cpp"
    echo "    java"
    echo "    python"
    echo ""
    echo "  Options:"
    echo "    --skip-collect         Skip Step 1 (LEARN) and Step 2 (TEST) collection"
    echo "    --skip-learn-collect   Skip Step 1 (LEARN collection) only"
    echo "    --skip-test-collect    Skip Step 2 (TEST collection) only"
    echo "    --learn-only           Run only Step 1 (LEARN collection) and exit"
    exit 1
fi

# 별칭 정규화
case "$1" in
    smallbasic|sb)      LANG="smallbasic" ;;
    c)                  LANG="c" ;;
    haskell)            LANG="haskell" ;;
    ruby)               LANG="ruby" ;;
    php)                LANG="php" ;;
    javascript|js)      LANG="javascript" ;;
    cpp)                LANG="cpp" ;;
    java)               LANG="java" ;;
    python)             LANG="python" ;;
    typescript|ts)      LANG="typescript" ;;
    *)
        echo "Error: Unknown language '$1'"
        echo "Supported: smallbasic(sb), c, haskell, ruby, php, javascript(js), cpp, java, python, typescript(ts)"
        exit 1
        ;;
esac

# =================[ 스크립트 매핑 ]=================
REBUILD_SCRIPT="$TS_DIR/rebuild_all.sh"
COLLECT_TEST="$TS_DIR/to_data_batch_collect_test.py"
MAKE_ANSWERS="$TS_DIR/to_json_per_file_test.py"
COVERAGE_LANG="$LANG"

# =================[ 요약 로그 설정 ]=================
# 터미널 출력은 그대로 유지하고, 각 단계의 최종 결과 줄만 이 파일에 기록한다.
# 환경변수 PIPELINE_SUMMARY_LOG가 설정되면 사용, 아니면 기본값
SUMMARY_LOG="${PIPELINE_SUMMARY_LOG:-$TS_DIR/pipeline_summary.log}"

# 헬퍼: python3 실행 → 터미널 출력 유지 + 패턴 일치 줄만 SUMMARY_LOG에 추가
_pylog() {
    local label="$1" pattern="$2"
    shift 2
    local tmp
    tmp=$(mktemp)
    python3 "$@" 2>&1 | tee "$tmp"
    printf "  [%s]\n" "$label" >> "$SUMMARY_LOG"
    grep -E "$pattern" "$tmp" >> "$SUMMARY_LOG" || true
    printf "\n" >> "$SUMMARY_LOG"
    rm -f "$tmp"
}

# 헬퍼: bash 실행 → 터미널 출력 유지 + 패턴 일치 줄만 SUMMARY_LOG에 추가
_shlog() {
    local label="$1" pattern="$2"
    shift 2
    local tmp
    tmp=$(mktemp)
    bash "$@" 2>&1 | tee "$tmp"
    printf "  [%s]\n" "$label" >> "$SUMMARY_LOG"
    grep -E "$pattern" "$tmp" >> "$SUMMARY_LOG" || true
    printf "\n" >> "$SUMMARY_LOG"
    rm -f "$tmp"
}

# =================[ 스크립트 존재 확인 ]=================
for script in "$REBUILD_SCRIPT" "$COLLECT_TEST" "$MAKE_ANSWERS" "$TS_DIR/evaluate_coverage.py"; do
    if [ ! -f "$script" ]; then
        echo "Error: Script not found: $script"
        exit 1
    fi
done

# =================[ 파이프라인 실행 ]=================
TOTAL_START=$(date +%s)

echo "============================================================"
echo "  Language : $LANG"
echo "  Start    : $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"
echo ""

# 요약 로그: 언어 헤더 기록
{
    printf "============================================================\n"
    printf "  Language : %s\n" "$LANG"
    printf "  Start    : %s\n" "$(date '+%Y-%m-%d %H:%M:%S')"
    printf "============================================================\n"
} >> "$SUMMARY_LOG"

# --- Step 1: LEARN 컬렉션 (빌드 + LEARN 데이터 수집 + DB 집계) ---
if [ "$SKIP_LEARN_COLLECT" = true ]; then
    echo ">>> [Step 1/4] LEARN collection  [SKIPPED]"
    echo ""
else
    # 캡처 대상: to_data_batch_collect_learn_* 완료 요약, to_json_aggregate_* 완료 줄
    echo ">>> [Step 1/4] LEARN collection"
    echo "    Script : $REBUILD_SCRIPT $LANG"
    STEP_START=$(date +%s)
    _shlog "Step1 learn_collect($LANG)" \
        '^\[\*\] (Completed\.|Done! JSON|Results are in)|^[[:space:]]+-[[:space:]]+(Success|Skipped|Total Found)' \
        "$REBUILD_SCRIPT" "$LANG"
    echo "    Elapsed: $(( $(date +%s) - STEP_START ))s"
    echo ""
fi

# --learn-only: Step 1만 수행 후 종료
if [ "$LEARN_ONLY" = true ]; then
    echo "============================================================"
    echo "  DONE : $LANG pipeline completed (--learn-only: Step 1 only)"
    echo "  Total Elapsed: $(( $(date +%s) - TOTAL_START ))s"
    echo "  End   : $(date '+%Y-%m-%d %H:%M:%S')"
    echo "============================================================"
    {
        printf "  Total Elapsed: %ss (learn-only)\n" "$(( $(date +%s) - TOTAL_START ))"
        printf "  End   : %s\n" "$(date '+%Y-%m-%d %H:%M:%S')"
        printf "\n"
    } >> "$SUMMARY_LOG"
    exit 0
fi

# --- Step 2: TEST 컬렉션 (TEST 데이터 수집) ---
if [ "$SKIP_TEST_COLLECT" = true ]; then
    echo ">>> [Step 2/4] TEST collection  [SKIPPED]"
    echo ""
else
    # 캡처 대상: [*] Completed. / - Success/Skipped/Total Found / [*] Results are in
    echo ">>> [Step 2/4] TEST collection"
    echo "    Script : $COLLECT_TEST $LANG"
    STEP_START=$(date +%s)
    cd "$TS_DIR" && _pylog "Step2 collect_test($LANG)" \
        '^\[\*\] (Completed\.|Results are in)|^[[:space:]]+-[[:space:]]+(Success|Skipped|Total Found)' \
        "$COLLECT_TEST" "$LANG"
    echo "    Elapsed: $(( $(date +%s) - STEP_START ))s"
    echo ""
fi

# --- Step 3: 정답지 생성 ---
# 캡처 대상: [*] All done. Processed N/N files.
echo ">>> [Step 3/4] Generate answer JSON"
echo "    Script : $MAKE_ANSWERS $LANG"
STEP_START=$(date +%s)
_pylog "Step3 make_answers($LANG)" \
    '^\[\*\] All done\.' \
    "$MAKE_ANSWERS" "$LANG"
echo "    Elapsed: $(( $(date +%s) - STEP_START ))s"
echo ""

# --- Step 4: 랭크 + 커버리지 평가 (통합) ---
# 캡처 대상: [Global] 통계 줄 / [LANG_UPPER] 통계 줄 / [Per-Project] 통계 줄 / [Saved] 줄
echo ">>> [Step 4/4] Evaluate (rank + coverage)"
echo "    Script : evaluate_coverage.py  (lang=$COVERAGE_LANG)"
[ "$PER_PROJECT" = true ] && echo "    Mode   : --per-project enabled"
STEP_START=$(date +%s)
EXTRA_ARGS=""
[ "$PER_PROJECT" = true ] && EXTRA_ARGS="$EXTRA_ARGS --per-project"
cd "$TS_DIR" && _pylog "Step4 evaluate($LANG)" \
    '^\[Global\]|\[[A-Z][A-Z0-9_-]*\] (Total Queries|Top-10 Count|Top11~20|Beyond Top|CPP Fail|Found[[:space:]]|Not Found|Fail[[:space:]]*)|\[Saved\]' \
    "$TS_DIR/evaluate_coverage.py" "$COVERAGE_LANG" $EXTRA_ARGS
echo "    Elapsed: $(( $(date +%s) - STEP_START ))s"
echo ""

echo "============================================================"
echo "  DONE : $LANG pipeline completed (4 steps)"
echo "  Total Elapsed: $(( $(date +%s) - TOTAL_START ))s"
echo "  End   : $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"

# 요약 로그: 언어 푸터 기록
{
    printf "  Total Elapsed: %ss\n" "$(( $(date +%s) - TOTAL_START ))"
    printf "  End   : %s\n" "$(date '+%Y-%m-%d %H:%M:%S')"
    printf "\n"
} >> "$SUMMARY_LOG"
