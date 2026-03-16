#!/bin/bash

# 에러 발생 시 즉시 중단
set -e

# =================[ 경로 설정 ]=================
ROOT="/home/hyeonjin/PL"
TS_DIR="$ROOT/tree-sitter"
LANG_DIR="$ROOT/tree-sitter-java"
EXT_DIR="$ROOT/code-completion-extension"

EXE_NAME="TreeSitterCutFile.exe"
TS_CLI="$TS_DIR/target/debug/tree-sitter"

echo "=== [0] Sanity Checks ==="
if [ ! -d "$TS_DIR" ]; then echo "Error: $TS_DIR not found"; exit 1; fi
if [ ! -d "$LANG_DIR" ]; then echo "Error: $LANG_DIR not found"; exit 1; fi

echo ""
echo "=== [1] Cargo Build (Tree-sitter CLI) ==="
cd "$TS_DIR"
cargo build
if [ ! -f "$TS_CLI" ]; then echo "Error: tree-sitter CLI build failed"; exit 1; fi

echo ""
echo "=== [2] Generate/Build (tree-sitter-java) ==="
cd "$LANG_DIR"

# Java 파서는 scanner.c가 없음 → src/ 전체 삭제 가능
# 단, 일관성을 위해 generate로 덮어써지는 파일들만 삭제
echo " -> Cleaning up old artifacts..."
rm -f src/parser.c
rm -f src/grammar.json
rm -f src/node-types.json
rm -rf src/tree_sitter/
rm -rf build/
rm -f *.so
rm -f LR_Items_Dump.txt

TOKEN_MAP_OUTPUT_DIR="$EXT_DIR/resources/java" "$TS_CLI" generate
"$TS_CLI" build

echo ""
echo "=== [3] Optional Parse Smoke Test ==="
SAMPLE_TMP="$TS_DIR/_smoke_test_java.java"
cat > "$SAMPLE_TMP" << 'EOF'
public class Hello {
    public static int add(int a, int b) {
        return a + b;
    }

    public static void main(String[] args) {
        System.out.println(add(1, 2));
    }
}
EOF
if "$TS_CLI" parse "$SAMPLE_TMP" --quiet 2>/dev/null; then
    echo " -> Parse test passed."
else
    echo " -> (warn) Parse test failed — skipping."
fi
rm -f "$SAMPLE_TMP"

echo ""
echo "=== [4] Rebuild TreeSitterCutFile (g++) ==="
cd "$TS_DIR"
rm -f *.o "$EXE_NAME"

echo " -> Compiling lib.c..."
gcc -c lib/src/lib.c \
    -Ilib/include -Ilib/src \
    -std=c99 -D_GNU_SOURCE -O2 -fPIC -o lib.o

echo " -> Compiling TreeSitterCutFile.cpp..."
g++ -c TreeSitterCutFile.cpp \
    -Ilib/include \
    -std=c++17 -O2 -fPIC -o main.o

echo " -> Linking..."
g++ -o "$EXE_NAME" main.o lib.o -ldl

if [ -f "$EXE_NAME" ]; then
    echo " -> Build success: $EXE_NAME"
else
    echo " -> Build failed"
    exit 1
fi

echo ""
echo "=== [5] Run Collection ==="
if [ -f "to_data_batch_collect_learn_java.py" ]; then
    python3 to_data_batch_collect_learn_java.py
    python3 to_json_aggregate_java.py
else
    echo " -> (skip) to_data_batch_collect_learn_java.py not found"
fi

echo ""
echo "=== [6] Rebuild VSCode Addon (.node) ==="
if [ -d "$EXT_DIR" ]; then
    cd "$EXT_DIR"

    if [ -f "package-lock.json" ]; then
        echo " -> Running npm ci..."
        npm ci
    else
        echo " -> Running npm install..."
        npm install
    fi

    echo " -> Running node-gyp rebuild..."
    npx node-gyp rebuild

    NODE_OUT="build/Release/java_parser_addon.node"
    if [ -f "$NODE_OUT" ]; then
        echo "✅ Addon built: $EXT_DIR/$NODE_OUT"
    else
        echo "⚠️  (warn) Addon output not found at $NODE_OUT"
    fi
else
    echo " -> (skip) Extension directory not found at: $EXT_DIR"
fi

echo ""
echo "✅ DONE: Full rebuild pipeline completed."
