import os
import glob
import json

# =================[ 설정 ]=================
INPUT_DIR = "..\\tree-sitter-smallbasic\\SB_Data_TS"
OUTPUT_DIR = "..\\moniExtension\Small-Basic-Extension\\src\\SB_EV_json"  # 폴더로 출력
# ==========================================

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
                    current_structure = format_pattern_clean(raw_candidate)
                    
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
                        "candidate": current_structure
                    }
                    
                    # 해당 State 블록의 첫 위치를 찾았으므로 플래그 끔
                    waiting_for_location = False

    return extracted_data

def main():
    if not os.path.exists(OUTPUT_DIR):
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