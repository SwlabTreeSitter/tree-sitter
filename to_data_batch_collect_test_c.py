# [Linux] 구조 후보 평가를 위한 TEST 데이터 컬렉션 스크립트
# For c11
#   1) .c    -> .data  <-- here
#   2) .data -> .json


import os
import subprocess
import shutil
import tempfile

# =================[ 리눅스 경로 설정 ]=================

# 1. 실행 파일 경로
EXE_PATH = "/home/hyeonjin/PL/tree-sitter/TreeSitterCutFile.exe"

# 2. [수정] C 언어 파서 라이브러리 (.so) 경로 (반드시 C용 .so로 변경)
LIB_PATH = "/home/hyeonjin/PL/tree-sitter-c/c.so" 

# 3. [수정] 테스트 프로그램들이 들어있는 루트 폴더
SOURCE_DIR = "/home/hyeonjin/PL/codecompletion_benchmarks/c11/TEST_BENCH/ansi_c" 

# 4. [수정] 결과 파일(.data)을 저장할 폴더
OUTPUT_DIR = "/home/hyeonjin/PL/benchmarks_collection/c11/TEST_BENCH_data"

# 5. 실행 인자 설정
ARG_LANG = "c"      # [수정] 언어 설정
ARG_ROW = "2147483647"  # 필요시 2147483647 로 변경 가능
ARG_COL = "0"
ARG_MODE = "1"      # 1 = Collection Mode

# 6. [추가] 수집할 확장자 및 무시할 폴더
TARGET_EXTENSIONS = {".c"}
IGNORE_DIRS = {".git", "build"}

# =========================================================

def main():
    if os.path.exists(OUTPUT_DIR):
        try:
            shutil.rmtree(OUTPUT_DIR) # rm -rf 와 동일한 역할
            print(f"[Info] Removed existing directory: {OUTPUT_DIR}")
        except Exception as e:
            print(f"[Error] Failed to remove directory: {e}")
            return

    # 결과 폴더 재생성
    os.makedirs(OUTPUT_DIR)
    print(f"[Info] Created output directory: {OUTPUT_DIR}")

    work_dir = tempfile.mkdtemp(prefix="collect_")
    print(f"[Info] Work dir: {work_dir}")

    # [추가] 스킵된 파일 목록 저장용 로그 파일 초기화
    SKIP_LOG_PATH = os.path.join(OUTPUT_DIR, "skipped_files.txt")
    with open(SKIP_LOG_PATH, "w", encoding="utf-8") as f:
        f.write("=== Skipped Files (Parse Error / Recovery Detected) ===\n")
    
    print(f"[*] Starting recursive scan in: {SOURCE_DIR}")

    success_count = 0
    skipped_count = 0
    total_found = 0

    # [수정] glob.glob 대신 os.walk를 사용하여 하위 폴더까지 재귀 탐색
    for root, dirs, files in os.walk(SOURCE_DIR):
        # 무시할 폴더 제외
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

        for filename in files:
            # [수정] 확장자 필터링 (.c 만 선택)
            _, ext = os.path.splitext(filename)
            if ext.lower() not in TARGET_EXTENSIONS:
                continue

            total_found += 1
            full_source_path = os.path.join(root, filename)

            # [수정] 파일명 중복 방지 로직 적용
            # 예: .../exercise_1_01/hello_world.c -> ansi_c_..._exercise_1_01_hello_world.c.data
            rel_path = os.path.relpath(full_source_path, SOURCE_DIR)
            safe_name = rel_path.replace(os.path.sep, "_").replace("..", "") + ".data"
            final_output_path = os.path.join(OUTPUT_DIR, safe_name)

            # [안전장치] 이전 루프의 잔여 파일 삭제
            generated_file = os.path.join(work_dir, "Test.data")
            if os.path.exists(generated_file):
                os.remove(generated_file)

            print(f"Processing: {rel_path} ...")

            # 1. EXE 실행
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
                
                # 1. stderr에서 [Skip] 메시지 감지
                if "[Skip]" in result.stderr:
                    is_skipped = True
                    skip_reason = "Syntax Error / High Cost"
                    print(f"  -> Detected SKIP signal: {result.stderr.strip()}")
                
                # 2. C++ 프로그램이 에러 코드로 종료된 경우
                elif result.returncode != 0:
                    is_skipped = True
                    skip_reason = f"Process Error (Exit Code {result.returncode})"
                    print(f"  -> Process failed: {result.stderr.strip()}")

            except Exception as e:
                is_skipped = True
                skip_reason = str(e)
                print(f"  -> Exception: {e}")

            # 2. 결과 파일 이동
            if not is_skipped and os.path.exists(generated_file) and os.path.getsize(generated_file) > 0:
                if os.path.exists(final_output_path):
                    os.remove(final_output_path)
                
                shutil.move(generated_file, final_output_path)
                success_count += 1
            else:
                 # 실패했거나 스킵된 경우
                skipped_count += 1
                
                # 잔여 파일 정리 (빈 파일이 생겼을 수 있음)
                if os.path.exists(generated_file):
                    os.remove(generated_file)
                
                # 로그 메시지 결정
                if not is_skipped: # 로직상 스킵은 아닌데 파일이 없는 경우
                    skip_reason = "No output generated or empty file"
                    print(f"  -> Failed: {skip_reason}")

                # 로그 기록
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