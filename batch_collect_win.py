import os
import subprocess
import shutil
import glob

# =================[ 윈도우 경로 설정 ]=================

# 1. 실행 파일 경로 (현재 폴더에 빌드된 파일)
EXE_PATH = ".\\TreeSitterCutFile.exe"

# 2. Small Basic 파서 라이브러리 (.dll) 경로
LIB_PATH = "..\\tree-sitter-smallbasic\\smallbasic.dll"

# 3. 샘플 프로그램(.sb)들이 들어있는 폴더
SOURCE_DIR = "..\\tree-sitter-smallbasic\\SB_Sample1"

# 4. 결과 파일(.data)을 저장할 폴더 (새로 생성될 폴더)
# ..\\tree-sitter-smallbasic\\SB_Data_TS
OUTPUT_DIR = "..\\tree-sitter-smallbasic\\SB_Data_TS1"

# 5. 실행 인자 설정
ARG_LANG = "smallbasic"
ARG_ROW = "9999999"  # 파일 끝까지 읽기
ARG_COL = "0"
ARG_MODE = "1"      # 1 = Collection Mode

# 스킵된 파일 목록을 저장할 로그 파일
SKIPPED_LOG_FILE = "skipped_files.txt"

# =========================================================

def main():
    # 결과 폴더 생성
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"[Info] Created output directory: {OUTPUT_DIR}")

    # 소스 폴더 내의 모든 .sb 파일 찾기
    sb_files = glob.glob(os.path.join(SOURCE_DIR, "*.sb"))
    
    if not sb_files:
        print(f"[Error] No .sb files found in {SOURCE_DIR}")
        return

    print(f"[*] Found {len(sb_files)} Small Basic files. Starting collection...")

    success_count = 0
    skipped_list = []

    for sb_file in sb_files:
        # 파일명 추출
        filename = os.path.basename(sb_file)
        # 확장자 변경 (.sb -> .data)
        output_filename = filename.replace(".sb", ".data")
        final_output_path = os.path.join(OUTPUT_DIR, output_filename)

        print(f"Processing: {filename} ...", end=" ")

        # 1. EXE 실행
        # 인자 순서: [EXE] [Lang] [LibPath] [FilePath] [Row] [Col] [Mode]
        cmd = [EXE_PATH, ARG_LANG, LIB_PATH, sb_file, ARG_ROW, ARG_COL, ARG_MODE]
        
        try:
            # check=False로 변경하여 에러 발생 시 예외가 아닌 returncode를 받음
            result = subprocess.run(
                cmd,
                check=False, 
                stdout=subprocess.DEVNULL, # 일반 출력은 숨김
                stderr=subprocess.PIPE     # 에러 메시지는 캡처
            )

            # Case A: 복구(Recovery) 발생 (Code 10) -> 스킵
            if result.returncode == 10:
                print("[Skipped] (Recovery Detected)")
                skipped_list.append(filename)
                
                # 혹시 생성된 쓰레기 파일이 있다면 삭제
                if os.path.exists("Test.data"):
                    os.remove("Test.data")
                continue

            # Case B: 기타 에러 (Code != 0) -> 실패 처리
            elif result.returncode != 0:
                print("[Failed]")
                err_msg = result.stderr.decode('utf-8', errors='replace').strip()
                if err_msg:
                    print(f"  Error: {err_msg}")
                else:
                    print(f"  Exit Code: {result.returncode}")
                continue

            # Case C: 성공 (Code 0) -> 파일 이동
            generated_file = "Test.data"
            
            if os.path.exists(generated_file):
                if os.path.exists(final_output_path):
                    os.remove(final_output_path)
                
                shutil.move(generated_file, final_output_path)
                print("Done.")
                success_count += 1
            else:
                print("[Failed] 'Test.data' was not created.")

        except Exception as e:
            print(f"[Error] Exception occurred: {str(e)}")
            continue
        # try:
        #     #실행
        #     subprocess.run(
        #         cmd,
        #         check=True,
        #         stdout=subprocess.DEVNULL, # 성공 시 출력 숨김
        #         stderr=subprocess.PIPE     # 에러 시만 출력 캡처
        #     )
        # except subprocess.CalledProcessError as e:
        #     print(f"[Failed]")
        #     print(f"  Error details: {e.stderr.decode('utf-8')}")
        #     continue

        # # 2. 결과 파일 이동
        # # C++ 프로그램은 현재 작업 디렉토리에 'Test.data'를 생성
        # generated_file = "Test.data" 
        
        # if os.path.exists(generated_file):
        #     if os.path.exists(final_output_path):
        #         os.remove(final_output_path)
            
        #     shutil.move(generated_file, final_output_path)
        #     print("Done.")
        #     success_count += 1
        # else:
        #     print("[Failed] 'Test.data' was not created.")

    print("-" * 50)
    print(f"[*] Completed. {success_count}/{len(sb_files)} files processed.")
    print(f"[*] Skipped files: {len(skipped_list)}")
    print(f"[*] Results are in: {OUTPUT_DIR}")

    # 스킵된 파일 목록 저장
    if skipped_list:
        with open(SKIPPED_LOG_FILE, "w", encoding="utf-8") as f:
            f.write(f"Total Skipped: {len(skipped_list)}\n")
            f.write("-" * 30 + "\n")
            for name in skipped_list:
                f.write(f"{name}\n")
        print(f"[*] Skipped file list saved to: {SKIPPED_LOG_FILE}")

if __name__ == "__main__":
    main()