#!/bin/bash

set -e

ROOT="/home/hyeonjin/PL"
TS_DIR="$ROOT/tree-sitter"
EXE_NAME="TreeSitterCutFile.exe"

echo "=== [1] Cargo Build (Tree-sitter lib) ==="
cd "$TS_DIR"
cargo build

echo ""
echo "=== [2] Rebuild TreeSitterCutFile (g++) ==="
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
echo "DONE."
