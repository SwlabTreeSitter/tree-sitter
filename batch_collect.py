import os
import subprocess
import shutil
import glob


# 1. 실행할 파서(TreeSitterCutFile.exe)의 경로
EXE_PATH = r"C:\PL\tree-sitter\TreeSitterCutFile.exe"

# 2. 샘플 프로그램(.sb)들이 들어있는 폴더
SOURCE_DIR = r"C:\PL\codecompletion_benchmarks\smallbasic\LEARN_BENCH"

# 3. 결과 파일(.data)을 저장할 폴더 (없으면 자동 생성됨)
OUTPUT_DIR = r"C:\PL\benchmarks_collection\smallbasic\LEARN_BENCH_data"

# 4. 실행 인자 설정
ARG_LANG = "smallbasic"
ARG_ROW = "999999"
ARG_COL = "0"
ARG_MODE = "1"

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

    for sb_file in sb_files:
        # 파일명 추출 (예: 01_HelloWorld.sb)
        filename = os.path.basename(sb_file)
        # 확장자 변경 (예: 01_HelloWorld.data)
        output_filename = filename.replace(".sb", ".data")
        final_output_path = os.path.join(OUTPUT_DIR, output_filename)

        print(f"Processing: {filename} ...", end=" ")

        # 1. EXE 실행 (Test.data 생성)
        # 명령어 예: TreeSitterCutFile.exe smallbasic C:\...\01_HelloWorld.sb 2 0 1
        try:
            subprocess.run(
                [EXE_PATH, ARG_LANG, sb_file, ARG_ROW, ARG_COL, ARG_MODE],
                check=True,
                stdout=subprocess.DEVNULL, # 불필요한 콘솔 출력 숨김
                stderr=subprocess.PIPE
            )
        except subprocess.CalledProcessError as e:
            print(f"[Failed] Execution error: {e}")
            continue

        # 2. 결과 파일(Test.data)을 찾아서 이름 변경 및 이동
        # C코드가 현재 작업 디렉토리에 Test.data를 생성하므로 거기서 찾습니다.
        # 주의: EXE가 있는 폴더나 스크립트 실행 위치에 생길 수 있습니다.
        generated_file = "Test.data" 
        
        if os.path.exists(generated_file):
            # 기존에 이미 파일이 있으면 덮어쓰기 위해 삭제
            if os.path.exists(final_output_path):
                os.remove(final_output_path)
            
            # 파일 이동 및 이름 변경
            shutil.move(generated_file, final_output_path)
            print("Done.")
            success_count += 1
        else:
            print("[Failed] 'Test.data' was not created.")

    print("-" * 50)
    print(f"[*] Completed. {success_count}/{len(sb_files)} files processed.")
    print(f"[*] Results are in: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()