import os
import subprocess
import shutil

# =================[ 설정 영역 ]=================

# 1. 실행 파일 경로
EXE_PATH = "/home/hyeonjin/PL/tree-sitter/TreeSitterCutFile.exe"

# 2. C 언어 파서 라이브러리 경로
LIB_PATH = "/home/hyeonjin/PL/tree-sitter-c/c.so" 

# 3. 소스 루트 폴더 (C11/LEARN_BENCH)
SOURCE_DIR = "/home/hyeonjin/PL/codecompletion_benchmarks/c11/LEARN_BENCH"

# 4. 결과 저장 폴더
OUTPUT_DIR = "/home/hyeonjin/PL/benchmarks_collection/c11/LEARN_BENCH_data"

# 5. 수집할 확장자 (엄격하게 .c와 .h만 지정)
TARGET_EXTENSIONS = {".c", ".h"}

# 6. 무시할 폴더명 (빌드 폴더)
IGNORE_DIRS = {"build"} 

ARG_ROW = "2147483647"  # 파일 끝까지 읽기
ARG_COL = "0"
ARG_MODE = "1"      # 1 = Collection Mode


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

    # [추가] 스킵된 파일 목록 저장용 로그 파일 초기화
    SKIP_LOG_PATH = os.path.join(OUTPUT_DIR, "skipped_files.txt")
    with open(SKIP_LOG_PATH, "w", encoding="utf-8") as f:
        f.write("=== Skipped Files (Parse Error / Recovery Detected) ===\n")
    
    print(f"[*] Starting recursive scan in: {SOURCE_DIR}")

    success_count = 0
    skipped_count = 0
    total_found = 0

    # 재귀 탐색 시작
    for root, dirs, files in os.walk(SOURCE_DIR):
        # 무시할 폴더는 탐색에서 제외
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

        for filename in files:
            # 확장자 검사
            _, ext = os.path.splitext(filename)
            if ext.lower() not in TARGET_EXTENSIONS:
                continue

            total_found += 1
            
            # 전체 경로 및 상대 경로 계산
            full_source_path = os.path.join(root, filename)
            rel_path = os.path.relpath(full_source_path, SOURCE_DIR)
            
            # [파일명 생성] ansi_c/cJSON/cJSON.c -> ansi_c_cJSON_cJSON.c.data
            safe_name = rel_path.replace(os.path.sep, "_").replace("..", "") + ".data"
            final_output_path = os.path.join(OUTPUT_DIR, safe_name)
            generated_file = "Test.data"

            # [안전장치] 이전 루프의 잔여 파일 삭제
            if os.path.exists(generated_file):
                os.remove(generated_file)

            print(f"Processing: {rel_path} ...")

            # 실행 명령어
            # args: [EXE] [Lang] [LibPath] [FilePath] [Row] [Col] [Mode]
            cmd = [EXE_PATH, "c", LIB_PATH, full_source_path, ARG_ROW, ARG_COL, ARG_MODE]

            is_skipped = False
            skip_reason = ""

            try:
                # [수정] check=False로 설정하여 에러 코드 발생 시에도 흐름 제어
                result = subprocess.run(
                    cmd, 
                    check=False, 
                    capture_output=True, 
                    text=True
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

            # =======================================================
            # 결과 처리 로직 (이동 or 스킵 기록)
            # =======================================================
            
            # 스킵 대상이 아니고, 파일이 생성되었으며, 내용이 있어야 함 (0바이트 방지)
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