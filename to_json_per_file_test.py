# [Linux] 구조 후보 평가를 위한 TEST 컬렉션 정답지 구성 스크립트
# For all languages (by 경로 수정)
#   1) .(lang) -> .data
#   2) .data   -> .json  <-- here

# 컬렉션 파일들(.data)을 읽어 
# 커서 위치별 state_id와 candidate 정보를 JSON으로 변환
# 개별 .data 파일 -> 개별 .json 파일 (reports/(language) 폴더)

# 예) reports\smallbasic\01_HelloWorld.json
#   "1,11": {
#     "state_id": 188,
#     "candidate": "[., ID, (, Exprs, )]"
#   },

import os
import glob
import json
import shutil

# =================[ 리눅스 경로 설정 ]=================
# INPUT_DIR = "/home/hyeonjin/PL/benchmarks_collection/smallbasic/TEST_BENCH_data2"
# OUTPUT_DIR = "/home/hyeonjin/PL/tree-sitter/reports/smallbasic"
INPUT_DIR = "/home/hyeonjin/PL/benchmarks_collection/c11/TEST_BENCH_data"
OUTPUT_DIR = "/home/hyeonjin/PL/tree-sitter/reports/c11"
# =========================================================

def format_pattern_clean(raw_pattern: str) -> str:
    """
    입력: "= ID . ID"
    출력: "[=, ID, ., ID]"
    """
    tokens = raw_pattern.split()
    return "[" + ", ".join(tokens) + "]"

def process_one_data_file(file_path: str) -> dict:
    """
    .data 파일을 읽어 Dictionary 반환
    key: location ("Row,Col")
    value: { "state_id": int, "candidate": str }
    """

    extracted_data = {}
    
    current_state = None
    current_structure = None
    
    # 플래그: State 라인을 읽은 직후, 첫 번째 Location만 잡기 위함
    waiting_for_location = False

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip()
            if not line: continue

            # 1. State & Candidate 라인 (들여쓰기 없음)
            # 예: "1 ID . ID ( Exprs )"
            if not line[0].isspace():
                parts = line.split(maxsplit=1)
                if parts and parts[0].isdigit():
                    current_state = int(parts[0])
                    raw_candidate = parts[1] if len(parts) > 1 else ""
                    
                    # 포맷 변환
                    # current_structure = format_pattern_clean(raw_candidate)
                    
                    # 다음 줄에서 위치를 찾으라고 신호
                    waiting_for_location = True
            
            # 2. Location & Lexeme 라인 (들여쓰기 있음)
            # 예: "  1,1: TextWindow"
            elif waiting_for_location and line.strip():
                if ":" in line:
                    # "  1,1: ..." -> "1,1" 추출
                    loc_part = line.split(":", 1)[0].strip()
                    
                    # 딕셔너리에 Key(Location)로 저장
                    extracted_data[loc_part] = {
                        "state_id": current_state,
                        "candidate": raw_candidate # current_structure
                    }
                    
                    # 해당 State 블록의 첫 위치를 찾았으므로 플래그 끔
                    waiting_for_location = False

    return extracted_data

def main():
    if os.path.exists(OUTPUT_DIR):
        try:
            shutil.rmtree(OUTPUT_DIR) # rm -rf 와 동일한 역할
            print(f"[Info] Removed existing directory: {OUTPUT_DIR}")
        except Exception as e:
            print(f"[Error] Failed to remove directory: {e}")
            return
    os.makedirs(OUTPUT_DIR)
    print(f"[Info] Created output directory: {OUTPUT_DIR}")


    data_files = glob.glob(os.path.join(INPUT_DIR, "*.data"))
    print(f"[*] Found {len(data_files)} files.")

    success_count = 0
    for data_file in data_files:
        filename = os.path.basename(data_file)
        json_filename = filename.replace(".data", ".json")
        output_path = os.path.join(OUTPUT_DIR, json_filename)
        
        try:
            result_dict = process_one_data_file(data_file)
            
            with open(output_path, "w", encoding="utf-8") as out:
                json.dump(result_dict, out, indent=2, ensure_ascii=False)
                
            print(f" -> Converted: {json_filename} ({len(result_dict)} keys)")
            success_count += 1
        except Exception as e:
            print(f"[Error] Failed to convert {filename}: {e}")

    print(f"[*] All done. Processed {success_count}/{len(data_files)} files.")

if __name__ == "__main__":
    main()