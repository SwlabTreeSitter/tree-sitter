import os
import glob
import json
from collections import defaultdict, Counter

# =================[ 설정 ]=================
INPUT_DIR = "..\\tree-sitter-smallbasic\\SB_Data_TS"
OUTPUT_DIR = "..\\moniExtension\Small-Basic-Extension\\src\\SB_DB_json"  # 폴더로 출력
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
                "key": format_pattern_clean(pattern),
                "value": count
            })
        result[str(state_id)] = items

    return result

def main():
    data_files = sorted(glob.glob(os.path.join(INPUT_DIR, "*.data")))
    if not data_files:
        print(f"[Error] No .data files found in {INPUT_DIR}")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
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
