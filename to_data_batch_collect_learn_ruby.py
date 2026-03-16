# [Linux] DB 구축 위한 LEARN 데이터 컬렉션 스크립트
# For ruby
#   1) .rb   -> .data  <-- here
#   2) .data -> .json

import os
import subprocess
import shutil

# =================[ 설정 영역 ]=================

# 1. 실행 파일 경로
EXE_PATH = "/home/hyeonjin/PL/tree-sitter/TreeSitterCutFile.exe"

# 2. Ruby 언어 파서 라이브러리 경로
LIB_PATH = "/home/hyeonjin/PL/tree-sitter-ruby/ruby.so"

# 3. 소스 루트 폴더 (ruby/LEARN)
SOURCE_DIR = "/home/hyeonjin/PL/codecompletion_benchmarks/ruby/LEARN"

# 4. 결과 저장 폴더
OUTPUT_DIR = "/home/hyeonjin/PL/benchmarks_collection/ruby/LEARN_data"

# 5. 수집할 확장자
TARGET_EXTENSIONS = {".rb"}

# 6. 무시할 폴더명 (학습 노이즈 제거)
IGNORE_DIRS = {
    # 공통: 빌드 및 테스트, 문서
    "test", "tests", "spec", "specs", "features",
    "doc", "docs", "documentation",
    "benchmark", "benchmarks", "bench",
    "example", "examples",
    # Ruby 특화
    "vendor", "node_modules", ".bundle",
    # 기타
    ".git", "script", "scripts",
}

ARG_ROW = "2147483647"  # 파일 끝까지 읽기
ARG_COL = "0"
ARG_MODE = "1"          # 1 = Collection Mode

# =========================================================

def main():
    if os.path.exists(OUTPUT_DIR):
        try:
            shutil.rmtree(OUTPUT_DIR)
            print(f"[Info] Removed existing directory: {OUTPUT_DIR}")
        except Exception as e:
            print(f"[Error] Failed to remove directory: {e}")
            return

    os.makedirs(OUTPUT_DIR)
    print(f"[Info] Created output directory: {OUTPUT_DIR}")

    SKIP_LOG_PATH = os.path.join(OUTPUT_DIR, "skipped_files.txt")
    with open(SKIP_LOG_PATH, "w", encoding="utf-8") as f:
        f.write("=== Skipped Files (Parse Error / Recovery Detected) ===\n")

    print(f"[*] Starting recursive scan in: {SOURCE_DIR}")

    success_count = 0
    skipped_count = 0
    total_found = 0

    for root, dirs, files in os.walk(SOURCE_DIR):
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
            generated_file = "Test.data"

            if os.path.exists(generated_file):
                os.remove(generated_file)

            print(f"Processing: {rel_path} ...")

            cmd = [EXE_PATH, "ruby", LIB_PATH, full_source_path, ARG_ROW, ARG_COL, ARG_MODE]

            is_skipped = False
            skip_reason = ""

            try:
                result = subprocess.run(
                    cmd,
                    check=False,
                    capture_output=True,
                    text=True
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
                    log_f.write(f"{rel_path}\n")

    print("\n" + "="*30)
    print(f"[*] SCAN COMPLETED")
    print(f"    - Processed: {success_count}")
    print(f"    - Skipped:   {skipped_count}")
    print(f"    - Total:     {total_found}")
    print(f"    - Saved in:  {OUTPUT_DIR}")
    print(f"    - Log file:  {SKIP_LOG_PATH}")
    print("="*30)

if __name__ == "__main__":
    main()
