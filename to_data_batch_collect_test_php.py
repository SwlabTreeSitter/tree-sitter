# [Linux] 구조 후보 평가를 위한 TEST 데이터 컬렉션 스크립트
# For php
#   1) .php  -> .data  <-- here
#   2) .data -> .json
#
# [수집 규칙]
#   - php-main/ (Exercism PHP Track):
#       .meta/example.php  : practice 연습문제 완성 풀이
#       .meta/exemplar.php : concept 연습문제 완성 풀이
#       → 위 두 패턴만 수집 (테스트 파일, 스텁 파일 제외)
#   - DesignPatternsPHP-main/, PHP-master/:
#       모든 .php 파일 수집

import os
import subprocess
import shutil
import tempfile

# =================[ 경로 설정 ]=================

# 1. 실행 파일 경로
EXE_PATH = "/home/hyeonjin/PL/tree-sitter/TreeSitterCutFile.exe"

# 2. PHP 언어 파서 라이브러리 경로
LIB_PATH = "/home/hyeonjin/PL/tree-sitter-php/php/parser.so"

# 3. 테스트 프로그램들이 들어있는 루트 폴더
SOURCE_DIR = "/home/hyeonjin/PL/codecompletion_benchmarks/php/TEST"

# 4. 결과 파일(.data)을 저장할 폴더
OUTPUT_DIR = "/home/hyeonjin/PL/benchmarks_collection/php/TEST_data"

# 5. Exercism 프로젝트 폴더명 (특별 수집 규칙 적용)
EXERCISM_PROJECT = "php-main"

# 6. 실행 인자 설정
ARG_LANG = "php"
ARG_ROW = "2147483647"
ARG_COL = "0"
ARG_MODE = "1"      # 1 = Collection Mode

# =========================================================

def is_exercism_target(rel_path: str) -> bool:
    """
    Exercism 프로젝트에서 수집 대상인지 판별.
    .meta/example.php  (practice 완성 풀이)
    .meta/exemplar.php (concept 완성 풀이)
    만 True 반환.
    """
    parts = rel_path.replace("\\", "/").split("/")
    # .../<exercise>/.meta/example.php 또는 exemplar.php
    if len(parts) >= 2:
        parent_dir = parts[-2]   # .meta
        filename   = parts[-1]   # example.php / exemplar.php
        if parent_dir == ".meta" and filename in ("example.php", "exemplar.php"):
            return True
    return False

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

    work_dir = tempfile.mkdtemp(prefix="collect_")
    print(f"[Info] Work dir: {work_dir}")

    SKIP_LOG_PATH = os.path.join(OUTPUT_DIR, "skipped_files.txt")
    with open(SKIP_LOG_PATH, "w", encoding="utf-8") as f:
        f.write("=== Skipped Files (Parse Error / Recovery Detected) ===\n")

    print(f"[*] Starting recursive scan in: {SOURCE_DIR}")

    success_count = 0
    skipped_count = 0
    total_found = 0

    for root, dirs, files in os.walk(SOURCE_DIR):
        # .git, vendor 등은 항상 제외
        dirs[:] = [d for d in dirs if d not in {".git", "vendor", "node_modules"}]

        for filename in files:
            _, ext = os.path.splitext(filename)
            if ext.lower() != ".php":
                continue

            full_source_path = os.path.join(root, filename)
            rel_path = os.path.relpath(full_source_path, SOURCE_DIR)
            # os.sep → '/' で統一して判定
            rel_path_unix = rel_path.replace(os.path.sep, "/")

            # --- 프로젝트별 수집 규칙 적용 ---
            top_project = rel_path_unix.split("/")[0]

            if top_project == EXERCISM_PROJECT:
                # Exercism: .meta/example.php, .meta/exemplar.php 만 수집
                if not is_exercism_target(rel_path_unix):
                    continue
            # DesignPatternsPHP-main, PHP-master: 모든 .php 수집 (필터 없음)

            total_found += 1

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
