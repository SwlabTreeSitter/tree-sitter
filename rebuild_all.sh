#!/bin/bash

# 에러 발생 시 즉시 중단
set -e

# =================[ 경로 설정 ]=================
# 사용자 환경에 맞게 수정됨
ROOT="/home/hyeonjin/PL"
TS_DIR="$ROOT/tree-sitter"
LANG_DIR="$ROOT/tree-sitter-smallbasic"
EXT_DIR="$ROOT/extension/small-basic-extension"

# 실행 파일 이름 (리눅스지만 편의상 .exe 붙여둠, 떼도 상관없음)
EXE_NAME="TreeSitterCutFile.exe" 
TS_CLI="$TS_DIR/target/debug/tree-sitter"

echo "=== [0] Sanity Checks ==="
# 디렉토리 존재 확인
if [ ! -d "$TS_DIR" ]; then echo "Error: $TS_DIR not found"; exit 1; fi
if [ ! -d "$LANG_DIR" ]; then echo "Error: $LANG_DIR not found"; exit 1; fi

echo ""
echo "=== [1] Cargo Build (Tree-sitter CLI) ==="
cd "$TS_DIR"
# cargo가 설치되어 있어야 함
cargo build
if [ ! -f "$TS_CLI" ]; then echo "Error: tree-sitter CLI build failed"; exit 1; fi

echo ""
echo "=== [2] Generate/Build (tree-sitter-smallbasic) ==="
cd "$LANG_DIR"

# 기존 산출물 완전 삭제 (Clean)
echo " -> Cleaning up old artifacts..."
rm -rf src/             # parser.c가 생성되는 폴더
rm -rf build/           # 컴파일된 객체 파일(.o) 폴더
rm -f binding.gyp       # 빌드 설정
rm -f *.so              # 리눅스 라이브러리
rm -f *.json            # 캐시 파일들
rm -f LR_Items_Dump.txt # 덤프 파일도 삭제

# 기존 리눅스용 라이브러리(.so) 빌드
"$TS_CLI" generate
"$TS_CLI" build

echo ""
echo "=== [3] Optional Parse Smoke Test ==="
SAMPLE="$LANG_DIR/SB_Sample/01_HelloWorld.sb"
if [ -f "$SAMPLE" ]; then
    "$TS_CLI" parse "$SAMPLE" --quiet
    echo " -> Parse test passed."
else
    echo " -> (skip) sample not found."
fi

echo ""
echo "=== [4] Rebuild TreeSitterCutFile (g++) ==="
cd "$TS_DIR"
# 기존 빌드 파일 정리
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
# -ldl 옵션 필수 (dlopen 사용 때문)
g++ -o "$EXE_NAME" main.o lib.o -ldl

if [ -f "$EXE_NAME" ]; then
    echo " -> Build success: $EXE_NAME"
else
    echo " -> Build failed"
    exit 1
fi

echo ""
echo "=== [5] Run Collection ==="
# Python 스크립트 실행
if [ -f "batch_collect_linux.py" ]; then
    python3 batch_collect_linux.py
    python3 aggregate_results_json.py
else
    echo " -> (skip) batch_collect.py not found"
fi

echo ""
echo "=== [6] Rebuild VSCode Addon (.node) ==="
# [추가된 로직] 확장 프로그램 폴더가 존재하는지 확인
if [ -d "$EXT_DIR" ]; then
    cd "$EXT_DIR"

    # 의존성 설치 (package-lock.json 유무에 따라 분기)
    if [ -f "package-lock.json" ]; then
        echo " -> Running npm ci..."
        npm ci
    else
        echo " -> Running npm install..."
        npm install
    fi

    # node-gyp 리빌드
    echo " -> Running node-gyp rebuild..."
    npx node-gyp rebuild

    # 산출물 확인
    NODE_OUT="build/Release/sb_parser_addon.node"
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