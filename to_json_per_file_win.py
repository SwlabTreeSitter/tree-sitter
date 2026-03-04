# [Windows] 개발중 윈도우에서 각 파일별 컬렉션 결과를 확인하기 위함
# For small basic
#   1) .sb   -> .data
#   2) .data -> .json  <-- here

# 컬렉션 파일들(.data)을 읽어 
# state별 패턴과 빈도 정보를 JSON으로 변환
# 개별 .data 파일 -> 개별 .json 파일 (SB_DB_TS1_json 폴더)

# 예) 01_HelloWorld.json
#   "188": [
#     {
#       "key": "[., ID, (, Exprs, )]",
#       "value": 1
#     }
#   ],


import os
import glob
import json
import shutil
from collections import defaultdict, Counter

# ====================[ 윈도우 경로 설정 ]====================
INPUT_DIR = "..\\tree-sitter-smallbasic\\SB_Data_TS2"
OUTPUT_DIR = "..\\moniExtension\Small-Basic-Extension\\src\\SB_DB_TS2_json"  # 폴더로 출력
# =========================================================

def format_pattern_clean(raw_pattern: str) -> str:
    """
    입력: "= ID . ID"
    출력: "[=, ID, ., ID]"
    """
    tokens = raw_pattern.split()
    return "[" + ", ".join(tokens) + "]"
    # return "[" + ", ".join(tokens) + "]"

def process_one_data_file(file_path: str) -> dict:
    """
    한 개의 .data 파일을 읽어서:
    {
      "0": [{"key": "...", "value": 123}, ...],
      "1": ...
    }
    형태로 리턴 (state별 value 내림차순 정렬)
    """
    # state -> Counter(pattern -> count)
    state_to_counter = defaultdict(Counter)

    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            parts = line.split(maxsplit=1)
            if not parts or not parts[0].isdigit():
                continue

            state_id = int(parts[0])
            pattern = parts[1].strip() if len(parts) > 1 else ""
            state_to_counter[state_id][pattern] += 1

    # JSON 출력 구조로 변환 (state 오름차순, 각 state 내부는 count 내림차순)
    result = {}
    for state_id in sorted(state_to_counter.keys()):
        counter = state_to_counter[state_id]
        items = []
        for pattern, count in counter.most_common():  # count desc
            items.append({
                "key": pattern,
                "value": count
            })
        result[str(state_id)] = items

    return result

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


    data_files = sorted(glob.glob(os.path.join(INPUT_DIR, "*.data")))
    if not data_files:
        print(f"[Error] No .data files found in {INPUT_DIR}")
        return
    print(f"[*] Found {len(data_files)} files.")

    success = 0
    for i, file_path in enumerate(data_files, 1):
        base = os.path.splitext(os.path.basename(file_path))[0]
        out_path = os.path.join(OUTPUT_DIR, base + ".json")

        try:
            result = process_one_data_file(file_path)
            with open(out_path, "w", encoding="utf-8") as out:
                json.dump(result, out, ensure_ascii=False, indent=2)

            success += 1
            if i % 50 == 0 or i == len(data_files):
                print(f"   - processed {i}/{len(data_files)}")
        except Exception as e:
            print(f"[Failed] {file_path}: {e}")

    print("-" * 60)
    print(f"[*] Done. {success}/{len(data_files)} JSON files written.")
    print(f"[*] Results are in: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
