import os
import subprocess
import shutil
import glob

# =================[ 리눅스 경로 설정 ]=================

# 1. 실행 파일 경로 (현재 폴더에 빌드된 파일)
EXE_PATH = "/home/hyeonjin/PL/tree-sitter/TreeSitterCutFile.exe"

# 2. Small Basic 파서 라이브러리 (.so) 경로
LIB_PATH = "/home/hyeonjin/PL/tree-sitter-smallbasic/smallbasic.so"

# 3. 샘플 프로그램(.sb)들이 들어있는 폴더 (LEARN/TEST)
SOURCE_DIR = "/home/hyeonjin/PL/codecompletion_benchmarks/smallbasic/TEST_BENCH" 

# 4. 결과 파일(.data)을 저장할 폴더 (새로 생성될 폴더) (LEARN/TEST)
OUTPUT_DIR = "/home/hyeonjin/PL/benchmarks_collection/smallbasic/TEST_BENCH_data"

# 5. 실행 인자 설정
ARG_LANG = "smallbasic"
ARG_ROW = "999999"  # 파일 끝까지 읽기
ARG_COL = "0"
ARG_MODE = "1"      # 1 = Collection Mode

# =========================================================

def main():
    # 결과 폴더 생성
    if not os.path.exists(OUTPUT_DIR):
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
    skipped_count = 0 # [추가]

    for sb_file in sb_files:
        # 파일명 추출
        filename = os.path.basename(sb_file)
        # 확장자 변경 (.sb -> .data)
        output_filename = filename.replace(".sb", ".data")
        final_output_path = os.path.join(OUTPUT_DIR, output_filename)

        # [수정] end=" " 제거 (로그 출력을 위해 줄바꿈 허용)
        print(f"Processing: {filename} ...")

        # 1. EXE 실행
        # 인자 순서: [EXE] [Lang] [LibPath] [FilePath] [Row] [Col] [Mode]
        cmd = [EXE_PATH, ARG_LANG, LIB_PATH, sb_file, ARG_ROW, ARG_COL, ARG_MODE]
        
        try:
            # 실행
            # subprocess.run(
            #     cmd,
            #     check=True,
            #     stdout=subprocess.DEVNULL, # 성공 시 출력 숨김
            #     stderr=subprocess.PIPE     # 에러 시만 출력 캡처
            # )
            # [수정] 실행 및 출력 캡처
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True, # stdout/stderr 캡처
                text=True            # 텍스트 모드
            )

            # C++ 프로그램이 stderr로 출력한 내용([SKIP] 메시지 등)이 있으면 출력
            if result.stderr:
                print(result.stderr.strip())

        except subprocess.CalledProcessError as e:
            print(f"[Failed]")
            err_msg = e.stderr
            if hasattr(err_msg, 'decode'):
                err_msg = err_msg.decode('utf-8')
            print(f"  Error details: {err_msg}")
            continue

        # 2. 결과 파일 이동
        # C++ 프로그램은 현재 작업 디렉토리에 'Test.data'를 생성
        generated_file = "Test.data" 
        
        if os.path.exists(generated_file):
            if os.path.exists(final_output_path):
                os.remove(final_output_path)
            
            shutil.move(generated_file, final_output_path)
            print("Done.")
            success_count += 1
        else:
            print("[Failed] 'Test.data' was not created.")
            skipped_count += 1

            # 로그 파일에 기록
            with open(SKIP_LOG_PATH, "a", encoding="utf-8") as log_f:
                log_f.write(f"{filename}\n")

    print(f"[*] Completed.")
    print(f"    - Success: {success_count}")
    print(f"    - Skipped: {skipped_count}")
    print(f"    - Total:   {len(sb_files)}")
    print(f"[*] Results are in: {OUTPUT_DIR}")
    print(f"[*] Skipped log: {SKIP_LOG_PATH}")

if __name__ == "__main__":
    main()