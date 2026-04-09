# [Linux] 구조 후보 평가를 위한 TEST 데이터 컬렉션 스크립트
# For haskell
#   1) .hs   -> .data  <-- here
#   2) .data -> .json
#
# 사용법:
#   python to_data_batch_collect_test_haskell.py              # 전체 재수집 (OUTPUT_DIR 초기화)
#   python to_data_batch_collect_test_haskell.py <project>    # 특정 프로젝트만 (기존 파일 유지)

import sys
import os
import subprocess
import shutil
import tempfile

# =================[ 경로 설정 ]=================

# 1. 실행 파일 경로
EXE_PATH = "/home/hyeonjin/PL/tree-sitter/TreeSitterCutFile.exe"

# 2. Haskell 언어 파서 라이브러리 경로
LIB_PATH = "/home/hyeonjin/PL/tree-sitter-haskell/haskell.so"

# 3. 테스트 프로그램들이 들어있는 루트 폴더
SOURCE_DIR = "/home/hyeonjin/PL/codecompletion_benchmarks/haskell/TEST"

# 4. 결과 파일(.data)을 저장할 폴더
OUTPUT_DIR = "/home/hyeonjin/PL/benchmarks_collection/haskell/TEST_data"

# 5. 실행 인자 설정
ARG_LANG = "haskell"
ARG_ROW = "2147483647"
ARG_COL = "0"
ARG_MODE = "1"      # 1 = Collection Mode

# 6. 수집할 확장자 및 무시할 폴더
TARGET_EXTENSIONS = {".hs"}
IGNORE_DIRS = {".git", "build", "dist", "dist-newstyle", ".stack-work"}

# =========================================================

def main():
    project = sys.argv[1] if len(sys.argv) > 1 else None

    if project:
        # 특정 프로젝트만: OUTPUT_DIR은 유지하고 해당 프로젝트 .data 파일만 교체
        scan_root = os.path.join(SOURCE_DIR, project)
        if not os.path.isdir(scan_root):
            print(f"[Error] Project directory not found: {scan_root}")
            print(f"Available: {', '.join(sorted(os.listdir(SOURCE_DIR)))}")
            return
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        # 해당 프로젝트의 기존 .data 파일 삭제
        prefix = project.replace(os.path.sep, "_") + "_"
        for f in os.listdir(OUTPUT_DIR):
            if f.startswith(prefix) and f.endswith(".data"):
                os.remove(os.path.join(OUTPUT_DIR, f))
                print(f"[Info] Removed old: {f}")
        print(f"[*] Project mode: {project}")
    else:
        # 전체 재수집: OUTPUT_DIR 초기화
        scan_root = SOURCE_DIR
        if os.path.exists(OUTPUT_DIR):
            try:
                shutil.rmtree(OUTPUT_DIR)
                print(f"[Info] Removed existing directory: {OUTPUT_DIR}")
            except Exception as e:
                print(f"[Error] Failed to remove directory: {e}")
                return
        os.makedirs(OUTPUT_DIR)
        print(f"[Info] Created output directory: {OUTPUT_DIR}")

    work_dir = tempfile.mkdtemp(prefix="collect_")
    print(f"[Info] Work dir: {work_dir}")

    SKIP_LOG_PATH = os.path.join(OUTPUT_DIR, "skipped_files.txt")
    mode = "a" if project else "w"
    with open(SKIP_LOG_PATH, mode, encoding="utf-8") as f:
        if not project:
            f.write("=== Skipped Files (Parse Error / Recovery Detected) ===\n")
        else:
            f.write(f"\n=== [{project}] ===\n")

    print(f"[*] Starting recursive scan in: {scan_root}")

    success_count = 0
    skipped_count = 0
    total_found = 0

    for root, dirs, files in os.walk(scan_root):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

        for filename in files:
            _, ext = os.path.splitext(filename)
            if ext.lower() not in TARGET_EXTENSIONS:
                continue

            total_found += 1
            full_source_path = os.path.join(root, filename)

            rel_path = os.path.relpath(full_source_path, SOURCE_DIR)
            safe_name = rel_path.replace(os.path.sep, "_").replace("..", "") + ".data"
            final_output_path = os.path.join(OUTPUT_DIR, safe_name)

            generated_file = os.path.join(work_dir, "Test.data")
            if os.path.exists(generated_file):
                os.remove(generated_file)

            print(f"Processing: {rel_path} ...")

            cmd = [EXE_PATH, ARG_LANG, LIB_PATH, full_source_path, ARG_ROW, ARG_COL, ARG_MODE]

            is_skipped = False
            skip_reason = ""

            try:
                result = subprocess.run(
                    cmd,
                    check=False,
                    capture_output=True,
                    text=True,
                    cwd=work_dir
                )

                if "[Skip]" in result.stderr:
                    is_skipped = True
                    skip_reason = "Syntax Error / High Cost"
                    print(f"  -> Detected SKIP signal: {result.stderr.strip()}")

                elif result.returncode != 0:
                    is_skipped = True
                    skip_reason = f"Process Error (Exit Code {result.returncode})"
                    print(f"  -> Process failed: {result.stderr.strip()}")

            except Exception as e:
                is_skipped = True
                skip_reason = str(e)
                print(f"  -> Exception: {e}")

            if not is_skipped and os.path.exists(generated_file) and os.path.getsize(generated_file) > 0:
                if os.path.exists(final_output_path):
                    os.remove(final_output_path)

                shutil.move(generated_file, final_output_path)
                success_count += 1
            else:
                skipped_count += 1

                if os.path.exists(generated_file):
                    os.remove(generated_file)

                if not is_skipped:
                    skip_reason = "No output generated or empty file"
                    print(f"  -> Failed: {skip_reason}")

                with open(SKIP_LOG_PATH, "a", encoding="utf-8") as log_f:
                    log_f.write(f"{rel_path} | {skip_reason}\n")

    shutil.rmtree(work_dir, ignore_errors=True)

    print(f"[*] Completed.")
    print(f"    - Success: {success_count}")
    print(f"    - Skipped: {skipped_count}")
    print(f"    - Total Found: {total_found}")
    print(f"[*] Results are in: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
