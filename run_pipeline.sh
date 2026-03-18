#!/bin/bash

# =============================================================
# run_pipeline.sh
# 언어명을 인자로 받아 rebuild_all → 구조 후보 평가까지 전체 파이프라인 실행
#
# 사용법:
#   ./run_pipeline.sh <언어>
#
# 지원 언어:
#   smallbasic   sb
#   c11          c
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

# =================[ 언어 인자 검증 ]=================
if [ $# -ne 1 ]; then
    echo "Usage: $0 <language>"
    echo ""
    echo "  Supported languages:"
    echo "    smallbasic  (alias: sb)"
    echo "    c11         (alias: c)"
    echo "    haskell"
    echo "    ruby"
    echo "    php"
    echo "    javascript  (alias: js)"
    echo "    cpp"
    echo "    java"
    echo "    python"
    exit 1
fi

# 별칭 정규화
case "$1" in
    smallbasic|sb)      LANG="smallbasic" ;;
    c11|c)              LANG="c11" ;;
    haskell)            LANG="haskell" ;;
    ruby)               LANG="ruby" ;;
    php)                LANG="php" ;;
    javascript|js)      LANG="javascript" ;;
    cpp)                LANG="cpp" ;;
    java)               LANG="java" ;;
    python)             LANG="python" ;;
    *)
        echo "Error: Unknown language '$1'"
        echo "Supported: smallbasic(sb), c11(c), haskell, ruby, php, javascript(js), cpp, java, python"
        exit 1
        ;;
esac

# =================[ 언어별 스크립트 매핑 ]=================
case "$LANG" in
    smallbasic)
        REBUILD_SCRIPT="$TS_DIR/rebuild_all.sh"
        COLLECT_TEST="$TS_DIR/to_data_batch_collect_test.py"
        MAKE_ANSWERS="$TS_DIR/to_json_per_file_test_sb.py"
        EVALUATE="$TS_DIR/evaluate_struct_smallbasic.py"
        COVERAGE_LANG="smallbasic"
        ;;
    c11)
        REBUILD_SCRIPT="$TS_DIR/rebuild_all_c.sh"
        COLLECT_TEST="$TS_DIR/to_data_batch_collect_test_c.py"
        MAKE_ANSWERS="$TS_DIR/to_json_per_file_test_c.py"
        EVALUATE="$TS_DIR/evaluate_struct_c.py"
        COVERAGE_LANG="c"
        ;;
    haskell)
        REBUILD_SCRIPT="$TS_DIR/rebuild_all_haskell.sh"
        COLLECT_TEST="$TS_DIR/to_data_batch_collect_test_haskell.py"
        MAKE_ANSWERS="$TS_DIR/to_json_per_file_test_haskell.py"
        EVALUATE="$TS_DIR/evaluate_struct_haskell.py"
        COVERAGE_LANG="haskell"
        ;;
    ruby)
        REBUILD_SCRIPT="$TS_DIR/rebuild_all_ruby.sh"
        COLLECT_TEST="$TS_DIR/to_data_batch_collect_test_ruby.py"
        MAKE_ANSWERS="$TS_DIR/to_json_per_file_test_ruby.py"
        EVALUATE="$TS_DIR/evaluate_struct_ruby.py"
        COVERAGE_LANG="ruby"
        ;;
    php)
        REBUILD_SCRIPT="$TS_DIR/rebuild_all_php.sh"
        COLLECT_TEST="$TS_DIR/to_data_batch_collect_test_php.py"
        MAKE_ANSWERS="$TS_DIR/to_json_per_file_test_php.py"
        EVALUATE="$TS_DIR/evaluate_struct_php.py"
        COVERAGE_LANG="php"
        ;;
    javascript)
        REBUILD_SCRIPT="$TS_DIR/rebuild_all_javascript.sh"
        COLLECT_TEST="$TS_DIR/to_data_batch_collect_test_javascript.py"
        MAKE_ANSWERS="$TS_DIR/to_json_per_file_test_javascript.py"
        EVALUATE="$TS_DIR/evaluate_struct_javascript.py"
        COVERAGE_LANG="javascript"
        ;;
    cpp)
        REBUILD_SCRIPT="$TS_DIR/rebuild_all_cpp.sh"
        COLLECT_TEST="$TS_DIR/to_data_batch_collect_test_cpp.py"
        MAKE_ANSWERS="$TS_DIR/to_json_per_file_test_cpp.py"
        EVALUATE="$TS_DIR/evaluate_struct_cpp.py"
        COVERAGE_LANG="cpp"
        ;;
    java)
        REBUILD_SCRIPT="$TS_DIR/rebuild_all_java.sh"
        COLLECT_TEST="$TS_DIR/to_data_batch_collect_test_java.py"
        MAKE_ANSWERS="$TS_DIR/to_json_per_file_test_java.py"
        EVALUATE="$TS_DIR/evaluate_struct_java.py"
        COVERAGE_LANG="java"
        ;;
    python)
        REBUILD_SCRIPT="$TS_DIR/rebuild_all_python.sh"
        COLLECT_TEST="$TS_DIR/to_data_batch_collect_test_python.py"
        MAKE_ANSWERS="$TS_DIR/to_json_per_file_test_python.py"
        EVALUATE="$TS_DIR/evaluate_struct_python.py"
        COVERAGE_LANG="python"
        ;;
esac

# =================[ 요약 로그 설정 ]=================
# 터미널 출력은 그대로 유지하고, 각 단계의 최종 결과 줄만 이 파일에 기록한다.
SUMMARY_LOG="$TS_DIR/pipeline_summary.log"

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
for script in "$REBUILD_SCRIPT" "$COLLECT_TEST" "$MAKE_ANSWERS" "$EVALUATE" "$TS_DIR/evaluate_coverage.py"; do
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

# --- Step 1: rebuild_all (빌드 + LEARN 컬렉션 + 집계) ---
# 캡처 대상: to_data_batch_collect_learn_* 완료 요약, to_json_aggregate_* 완료 줄
echo ">>> [Step 1/5] rebuild_all"
echo "    Script : $REBUILD_SCRIPT"
STEP_START=$(date +%s)
_shlog "Step1 rebuild($LANG)" \
    '^\[\*\] (Completed\.|Done! JSON|Results are in)|^[[:space:]]+-[[:space:]]+(Success|Skipped|Total Found)' \
    "$REBUILD_SCRIPT"
echo "    Elapsed: $(( $(date +%s) - STEP_START ))s"
echo ""

# --- Step 2: TEST 데이터 수집 ---
# 캡처 대상: [*] Completed. / - Success/Skipped/Total Found / [*] Results are in
echo ">>> [Step 2/5] Collect TEST data"
echo "    Script : $COLLECT_TEST"
STEP_START=$(date +%s)
cd "$TS_DIR" && _pylog "Step2 collect_test($LANG)" \
    '^\[\*\] (Completed\.|Results are in)|^[[:space:]]+-[[:space:]]+(Success|Skipped|Total Found)' \
    "$COLLECT_TEST"
echo "    Elapsed: $(( $(date +%s) - STEP_START ))s"
echo ""

# --- Step 3: 정답지 생성 ---
# 캡처 대상: [*] All done. Processed N/N files.
echo ">>> [Step 3/5] Generate answer JSON"
echo "    Script : $MAKE_ANSWERS"
STEP_START=$(date +%s)
_pylog "Step3 make_answers($LANG)" \
    '^\[\*\] All done\.' \
    "$MAKE_ANSWERS"
echo "    Elapsed: $(( $(date +%s) - STEP_START ))s"
echo ""

# --- Step 4: 구조 후보 평가 ---
# 캡처 대상: [Global] 통계 줄 / [Saved] File Report 줄
echo ">>> [Step 4/5] Evaluate struct candidates"
echo "    Script : $EVALUATE"
STEP_START=$(date +%s)
_pylog "Step4 evaluate_struct($LANG)" \
    '^\[Global\]|\[Saved\] File Report' \
    "$EVALUATE"
echo "    Elapsed: $(( $(date +%s) - STEP_START ))s"
echo ""

# --- Step 5: 커버리지 평가 ---
# 캡처 대상: [LANG_UPPER] Total Queries/Found/Not Found/Fail / [Saved] CSV 줄
echo ">>> [Step 5/5] Evaluate coverage"
echo "    Script : evaluate_coverage.py  (lang=$COVERAGE_LANG)"
STEP_START=$(date +%s)
cd "$TS_DIR" && _pylog "Step5 evaluate_coverage($LANG)" \
    '^\[[A-Z][A-Z0-9]*\] (Total Queries|Found[[:space:]]|Not Found|Fail[[:space:]]*)|\[Saved\]' \
    "$TS_DIR/evaluate_coverage.py" "$COVERAGE_LANG"
echo "    Elapsed: $(( $(date +%s) - STEP_START ))s"
echo ""

echo "============================================================"
echo "  DONE : $LANG pipeline completed"
echo "  Total Elapsed: $(( $(date +%s) - TOTAL_START ))s"
echo "  End   : $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"

# 요약 로그: 언어 푸터 기록
{
    printf "  Total Elapsed: %ss\n" "$(( $(date +%s) - TOTAL_START ))"
    printf "  End   : %s\n" "$(date '+%Y-%m-%d %H:%M:%S')"
    printf "\n"
} >> "$SUMMARY_LOG"
