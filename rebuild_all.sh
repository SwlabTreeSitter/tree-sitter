#!/bin/bash
#
# 통합 rebuild 스크립트: 언어를 인자로 받아 전체 파이프라인을 실행한다.
# 여러 터미널에서 다른 언어를 동시 실행할 수 있도록 flock으로 공유 자원을 보호한다.
#
# 사용법:
#   ./rebuild_all.sh c
#   ./rebuild_all.sh haskell
#   ./rebuild_all.sh php
#

set -e

LANG="$1"
if [ -z "$LANG" ]; then
    echo "Usage: ./rebuild_all.sh <language>"
    echo ""
    echo "지원 언어 (resources/ 기준):"
    ls -1 "$ROOT/code-completion-extension/resources/" 2>/dev/null || echo "  (확인 불가)"
    exit 1
fi

# =================[ 경로 설정 ]=================
ROOT="/home/hyeonjin/PL"
TS_DIR="$ROOT/tree-sitter"
EXT_DIR="$ROOT/code-completion-extension"
EXE_NAME="TreeSitterCutFile.exe"
TS_CLI="$TS_DIR/target/debug/tree-sitter"
LOCK_DIR="/tmp/rebuild_all_locks"
mkdir -p "$LOCK_DIR"

# 언어별 문법 디렉토리 결정
# php, typescript는 하위 디렉토리 구조가 다름
case "$LANG" in
    php)        GRAMMAR_DIR="$ROOT/tree-sitter-php/php" ;;
    typescript) GRAMMAR_DIR="$ROOT/tree-sitter-typescript/typescript" ;;
    *)          GRAMMAR_DIR="$ROOT/tree-sitter-$LANG" ;;
esac

echo "=== rebuild_all.sh: $LANG ==="
echo "  GRAMMAR_DIR: $GRAMMAR_DIR"

# =================[ [0] Sanity Checks ]=================
echo ""
echo "=== [0] Sanity Checks ==="
if [ ! -d "$TS_DIR" ]; then echo "Error: $TS_DIR not found"; exit 1; fi
if [ ! -d "$GRAMMAR_DIR" ]; then echo "Error: $GRAMMAR_DIR not found"; exit 1; fi

# =================[ [1] Cargo Build ]=================
echo ""
echo "=== [1] Cargo Build (Tree-sitter CLI) ==="
flock "$LOCK_DIR/cargo.lock" bash -c "
    cd \"$TS_DIR\"
    cargo build
    if [ ! -f \"$TS_CLI\" ]; then echo 'Error: tree-sitter CLI build failed'; exit 1; fi
    echo ' -> cargo build done.'
"

# =================[ [2] Generate/Build ]=================
echo ""
echo "=== [2] Generate/Build (tree-sitter-$LANG) ==="
cd "$GRAMMAR_DIR"

echo " -> Cleaning up old artifacts..."
if [ -f "$GRAMMAR_DIR/src/scanner.c" ] || [ -f "$GRAMMAR_DIR/src/scanner.cc" ]; then
    # scanner가 있는 언어: 선택적 삭제 (scanner.c 보존)
    rm -f src/parser.c
    rm -f src/grammar.json
    rm -f src/node-types.json
    rm -rf src/tree_sitter/
else
    # scanner가 없는 언어: src/ 전체 삭제
    rm -rf src/
fi
rm -rf build/
rm -f *.so
rm -f LR_Items_Dump.txt

# token_mapping.json을 extension resources에 직접 생성
mkdir -p "$EXT_DIR/resources/$LANG"
TOKEN_MAP_OUTPUT_DIR="$EXT_DIR/resources/$LANG" "$TS_CLI" generate
"$TS_CLI" build
echo " -> Generate/Build done."

# =================[ [3] Smoke Test ]=================
echo ""
echo "=== [3] Optional Parse Smoke Test ==="
# examples/ 디렉토리에서 첫 번째 파일을 찾아 테스트
SAMPLE=$(find "$GRAMMAR_DIR/examples" -type f 2>/dev/null | head -1)
if [ -n "$SAMPLE" ]; then
    if "$TS_CLI" parse "$SAMPLE" --quiet 2>/dev/null; then
        echo " -> Parse test passed: $(basename "$SAMPLE")"
    else
        echo " -> (warn) Parse test failed — skipping."
    fi
else
    echo " -> (skip) No sample files in examples/."
fi

# =================[ [4] Rebuild TreeSitterCutFile ]=================
echo ""
echo "=== [4] Rebuild TreeSitterCutFile (g++) ==="
flock "$LOCK_DIR/gcc.lock" bash -c "
    cd \"$TS_DIR\"
    BUILD_TMP=\"build_\$\$\"
    rm -f \"\${BUILD_TMP}_lib.o\" \"\${BUILD_TMP}_main.o\" \"\${BUILD_TMP}_exe\"

    echo ' -> Compiling lib.c...'
    gcc -c lib/src/lib.c \\
        -Ilib/include -Ilib/src \\
        -std=c99 -D_GNU_SOURCE -O2 -fPIC -o \"\${BUILD_TMP}_lib.o\"

    echo ' -> Compiling TreeSitterCutFile.cpp...'
    g++ -c TreeSitterCutFile.cpp \\
        -Ilib/include \\
        -std=c++17 -O2 -fPIC -o \"\${BUILD_TMP}_main.o\"

    echo ' -> Linking...'
    g++ -o \"\${BUILD_TMP}_exe\" \"\${BUILD_TMP}_main.o\" \"\${BUILD_TMP}_lib.o\" -ldl

    if [ -f \"\${BUILD_TMP}_exe\" ]; then
        mv -f \"\${BUILD_TMP}_exe\" \"$EXE_NAME\"
        echo ' -> Build success: $EXE_NAME'
        rm -f \"\${BUILD_TMP}_lib.o\" \"\${BUILD_TMP}_main.o\"
    else
        rm -f \"\${BUILD_TMP}_lib.o\" \"\${BUILD_TMP}_main.o\" \"\${BUILD_TMP}_exe\"
        echo ' -> Build failed'
        exit 1
    fi
"

# =================[ [5] Run Collection ]=================
echo ""
echo "=== [5] Run Collection ==="
cd "$TS_DIR"
python3 to_data_batch_collect_learn.py "$LANG"
python3 to_json_aggregate.py "$LANG"

# =================[ [6] Rebuild VSCode Addon ]=================
echo ""
echo "=== [6] Rebuild VSCode Addon (.node) ==="
if [ -d "$EXT_DIR" ]; then
    flock "$LOCK_DIR/node-gyp.lock" bash -c "
        cd \"$EXT_DIR\"

        if [ -f 'package-lock.json' ]; then
            echo ' -> Running npm ci...'
            npm ci
        else
            echo ' -> Running npm install...'
            npm install
        fi

        echo ' -> Generating build config (binding.gyp, addon.cc)...'
        python3 generate_build_config.py

        echo ' -> Running node-gyp rebuild...'
        npx node-gyp rebuild

        echo ' -> Addon rebuild done.'
    "
else
    echo " -> (skip) Extension directory not found at: $EXT_DIR"
fi

echo ""
echo "DONE: rebuild_all.sh $LANG completed."
