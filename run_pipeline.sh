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
        ;;
    c11)
        REBUILD_SCRIPT="$TS_DIR/rebuild_all_c.sh"
        COLLECT_TEST="$TS_DIR/to_data_batch_collect_test_c.py"
        MAKE_ANSWERS="$TS_DIR/to_json_per_file_test_c.py"
        EVALUATE="$TS_DIR/evaluate_struct_c.py"
        ;;
    haskell)
        REBUILD_SCRIPT="$TS_DIR/rebuild_all_haskell.sh"
        COLLECT_TEST="$TS_DIR/to_data_batch_collect_test_haskell.py"
        MAKE_ANSWERS="$TS_DIR/to_json_per_file_test_haskell.py"
        EVALUATE="$TS_DIR/evaluate_struct_haskell.py"
        ;;
    ruby)
        REBUILD_SCRIPT="$TS_DIR/rebuild_all_ruby.sh"
        COLLECT_TEST="$TS_DIR/to_data_batch_collect_test_ruby.py"
        MAKE_ANSWERS="$TS_DIR/to_json_per_file_test_ruby.py"
        EVALUATE="$TS_DIR/evaluate_struct_ruby.py"
        ;;
    php)
        REBUILD_SCRIPT="$TS_DIR/rebuild_all_php.sh"
        COLLECT_TEST="$TS_DIR/to_data_batch_collect_test_php.py"
        MAKE_ANSWERS="$TS_DIR/to_json_per_file_test_php.py"
        EVALUATE="$TS_DIR/evaluate_struct_php.py"
        ;;
    javascript)
        REBUILD_SCRIPT="$TS_DIR/rebuild_all_javascript.sh"
        COLLECT_TEST="$TS_DIR/to_data_batch_collect_test_javascript.py"
        MAKE_ANSWERS="$TS_DIR/to_json_per_file_test_javascript.py"
        EVALUATE="$TS_DIR/evaluate_struct_javascript.py"
        ;;
    cpp)
        REBUILD_SCRIPT="$TS_DIR/rebuild_all_cpp.sh"
        COLLECT_TEST="$TS_DIR/to_data_batch_collect_test_cpp.py"
        MAKE_ANSWERS="$TS_DIR/to_json_per_file_test_cpp.py"
        EVALUATE="$TS_DIR/evaluate_struct_cpp.py"
        ;;
    java)
        REBUILD_SCRIPT="$TS_DIR/rebuild_all_java.sh"
        COLLECT_TEST="$TS_DIR/to_data_batch_collect_test_java.py"
        MAKE_ANSWERS="$TS_DIR/to_json_per_file_test_java.py"
        EVALUATE="$TS_DIR/evaluate_struct_java.py"
        ;;
    python)
        REBUILD_SCRIPT="$TS_DIR/rebuild_all_python.sh"
        COLLECT_TEST="$TS_DIR/to_data_batch_collect_test_python.py"
        MAKE_ANSWERS="$TS_DIR/to_json_per_file_test_python.py"
        EVALUATE="$TS_DIR/evaluate_struct_python.py"
        ;;
esac

# =================[ 스크립트 존재 확인 ]=================
for script in "$REBUILD_SCRIPT" "$COLLECT_TEST" "$MAKE_ANSWERS" "$EVALUATE"; do
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

# --- Step 1: rebuild_all (빌드 + LEARN 컬렉션 + 집계) ---
echo ">>> [Step 1/4] rebuild_all"
echo "    Script : $REBUILD_SCRIPT"
STEP_START=$(date +%s)
bash "$REBUILD_SCRIPT"
echo "    Elapsed: $(( $(date +%s) - STEP_START ))s"
echo ""

# --- Step 2: TEST 데이터 수집 ---
echo ">>> [Step 2/4] Collect TEST data"
echo "    Script : $COLLECT_TEST"
STEP_START=$(date +%s)
cd "$TS_DIR" && python3 "$COLLECT_TEST"
echo "    Elapsed: $(( $(date +%s) - STEP_START ))s"
echo ""

# --- Step 3: 정답지 생성 ---
echo ">>> [Step 3/4] Generate answer JSON"
echo "    Script : $MAKE_ANSWERS"
STEP_START=$(date +%s)
python3 "$MAKE_ANSWERS"
echo "    Elapsed: $(( $(date +%s) - STEP_START ))s"
echo ""

# --- Step 4: 구조 후보 평가 ---
echo ">>> [Step 4/4] Evaluate struct candidates"
echo "    Script : $EVALUATE"
STEP_START=$(date +%s)
python3 "$EVALUATE"
echo "    Elapsed: $(( $(date +%s) - STEP_START ))s"
echo ""

echo "============================================================"
echo "  DONE : $LANG pipeline completed"
echo "  Total Elapsed: $(( $(date +%s) - TOTAL_START ))s"
echo "  End   : $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"
