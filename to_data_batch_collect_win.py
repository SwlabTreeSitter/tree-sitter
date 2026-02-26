# [Windows] 개발중 윈도우에서 각 파일별 컬렉션 결과를 확인하기 위함
# For small basic
#   1) .sb   -> .data  <-- here
#   2) .data -> .json

# TreeSitterCutFile.exe 컬렉션 모드
# SB_Sample 폴더 내의 .sb 파일들 -> .data 로 컬렉션 (SB_Data_TS1 폴더)

# 예) 01_HelloWorld.data
# 188 . ID ( Exprs )
#   1,11: 
#   1,12: 
#   ...


import os
import subprocess
import shutil
import glob

# ====================[ 윈도우 경로 설정 ]====================

# 1. 실행 파일 경로 (현재 폴더에 빌드된 파일)
EXE_PATH = ".\\TreeSitterCutFile.exe"

# 2. Small Basic 파서 라이브러리 (.dll) 경로
LIB_PATH = "..\\tree-sitter-smallbasic\\smallbasic.dll"

# 3. 샘플 프로그램(.sb)들이 들어있는 폴더
SOURCE_DIR = "..\\tree-sitter-smallbasic\\SB_Sample"

# 4. 결과 파일(.data)을 저장할 폴더 (새로 생성될 폴더)
OUTPUT_DIR = "..\\tree-sitter-smallbasic\\SB_Data_TS1"

# 5. 실행 인자 설정
ARG_LANG = "smallbasic"
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

    # 소스 폴더 내의 모든 .sb 파일 찾기
    sb_files = glob.glob(os.path.join(SOURCE_DIR, "*.sb"))
    
    if not sb_files:
        print(f"[Error] No .sb files found in {SOURCE_DIR}")
        return

    print(f"[*] Found {len(sb_files)} Small Basic files. Starting collection...")

    success_count = 0
    skipped_count = 0

    for sb_file in sb_files:
        # 파일명 추출
        filename = os.path.basename(sb_file)
        # 확장자 변경 (.sb -> .data)
        output_filename = filename.replace(".sb", ".data")
        final_output_path = os.path.join(OUTPUT_DIR, output_filename)
        generated_file = "Test.data"

        # [안전장치] 이전 루프의 잔여 파일 삭제
        if os.path.exists(generated_file):
            os.remove(generated_file)

        print(f"Processing: {filename} ...")

        # 1. EXE 실행
        # 인자 순서: [EXE] [Lang] [LibPath] [FilePath] [Row] [Col] [Mode]
        cmd = [EXE_PATH, ARG_LANG, LIB_PATH, sb_file, ARG_ROW, ARG_COL, ARG_MODE]
        
        is_skipped = False
        skip_reason = ""

        try:
            # 실행
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True, # stdout(DEBUG 로그)과 stderr(에러/SKIP) 모두 캡처
                text=True            # 바이너리가 아닌 텍스트 문자열로 받음
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
        # C++ 프로그램은 현재 작업 디렉토리에 'Test.data'를 생성
        if not is_skipped and os.path.exists(generated_file) and os.path.getsize(generated_file) > 0:
            if os.path.exists(final_output_path):
                os.remove(final_output_path)
            
            shutil.move(generated_file, final_output_path)
            # print("  -> Done.")
            success_count += 1
        else:
            # 실패했거나 스킵된 경우
            skipped_count += 1
            
            # 잔여 파일 정리 (빈 파일이 생겼을 수 있음)
            if os.path.exists(generated_file):
                os.remove(generated_file)
            
            # 로그 메시지 결정
            if not is_skipped: # is_skipped는 false인데 파일이 없거나 0바이트인 경우
                skip_reason = "No output generated or empty file"
                print(f"  -> Failed: {skip_reason}")

            # 로그 기록
            with open(SKIP_LOG_PATH, "a", encoding="utf-8") as log_f:
                log_f.write(f"{filename} | {skip_reason}\n")

    print(f"[*] Completed.")
    print(f"    - Success: {success_count}")
    print(f"    - Skipped: {skipped_count}")
    print(f"    - Total:   {len(sb_files)}")
    print(f"[*] Results are in: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()