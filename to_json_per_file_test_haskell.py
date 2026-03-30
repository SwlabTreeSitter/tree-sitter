# [Linux] 구조 후보 평가를 위한 TEST 컬렉션 정답지 구성 스크립트 (Haskell 전용)
#   1) .hs -> .data
#   2) .data -> .json  <-- here
#
# 사용법:
#   python to_json_per_file_test_haskell.py              # 전체 변환 (OUTPUT_DIR 초기화)
#   python to_json_per_file_test_haskell.py <project>    # 특정 프로젝트만 (기존 파일 유지)

import sys
import os
import glob
import json
import shutil

# =================[ 경로 설정 ]=================
INPUT_DIR  = "/home/hyeonjin/PL/benchmarks_collection/haskell/TEST_data"
OUTPUT_DIR = "/home/hyeonjin/PL/tree-sitter/reports/haskell"
# ================================================

def process_one_data_file(file_path: str) -> dict:
    """
    .data 파일을 읽어 Dictionary 반환
    key: location ("Row,Col")
    value: [{ "state_id": int, "candidate": str }, ...]  (모든 항목 포함)
    """
    extracted_data = {}

    current_state = None
    raw_candidate = ""
    waiting_for_location = False

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip()
            if not line: continue

            # 1. State & Candidate 라인 (들여쓰기 없음)
            if not line[0].isspace():
                parts = line.split(maxsplit=1)
                if parts and parts[0].isdigit():
                    current_state = int(parts[0])
                    raw_candidate = parts[1] if len(parts) > 1 else ""
                    waiting_for_location = True

            # 2. Location & Lexeme 라인 (들여쓰기 있음)
            elif waiting_for_location and line.strip():
                if ":" in line:
                    loc_part = line.split(":", 1)[0].strip()
                    if loc_part not in extracted_data:
                        extracted_data[loc_part] = []
                    extracted_data[loc_part].append({
                        "state_id": current_state,
                        "candidate": raw_candidate
                    })
                    waiting_for_location = False

    return extracted_data

def main():
    project = sys.argv[1] if len(sys.argv) > 1 else None

    if project:
        # 특정 프로젝트만: OUTPUT_DIR 유지, 해당 프로젝트 .json만 교체
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        prefix = project.replace(os.path.sep, "_") + "_"
        # 기존 해당 프로젝트 .json 삭제
        for f in os.listdir(OUTPUT_DIR):
            if f.startswith(prefix) and f.endswith(".json"):
                os.remove(os.path.join(OUTPUT_DIR, f))
                print(f"[Info] Removed old: {f}")
        data_files = [
            f for f in glob.glob(os.path.join(INPUT_DIR, "*.data"))
            if os.path.basename(f).startswith(prefix)
        ]
        print(f"[*] Project mode: {project} ({len(data_files)} .data files)")
    else:
        # 전체 변환: OUTPUT_DIR 초기화
        if os.path.exists(OUTPUT_DIR):
            try:
                shutil.rmtree(OUTPUT_DIR)
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
