#!/usr/bin/env python3
"""
TEST 컬렉션 정답지 구성 통합 스크립트.
.data 파일을 개별 .json 파일로 변환한다.

사용법:
  python3 to_json_per_file_test.py <language>              # 전체 변환
  python3 to_json_per_file_test.py <language> <project>    # 특정 프로젝트만
"""

import sys
import os
import glob
import json
import shutil

# =================[ 경로 설정 ]=================
ROOT = "/home/hyeonjin/PL"
TS_DIR = os.path.join(ROOT, "tree-sitter")


def process_one_data_file(file_path: str) -> dict:
    """
    .data 파일을 읽어 Dictionary 반환
    key: location (바이트 오프셋 문자열)
    value: [{ "state_id": int, "candidate": str }, ...]
    """
    extracted_data = {}

    current_state = None
    raw_candidate = ""
    waiting_for_location = False

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip()
            if not line:
                continue

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
                    loc_part = line.split(":", 1)[0].strip().lstrip("@")
                    if loc_part not in extracted_data:
                        extracted_data[loc_part] = []
                    extracted_data[loc_part].append({
                        "state_id": current_state,
                        "candidate": raw_candidate
                    })
                    waiting_for_location = False

    return extracted_data


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 to_json_per_file_test.py <language> [project]")
        sys.exit(1)

    lang = sys.argv[1]
    project = sys.argv[2] if len(sys.argv) > 2 else None

    input_dir = os.path.join(ROOT, "benchmarks_collection", lang, "TEST_data")
    output_dir = os.path.join(TS_DIR, "reports", lang)

    if not os.path.isdir(input_dir):
        print(f"[Error] Input directory not found: {input_dir}")
        sys.exit(1)

    if project:
        # 특정 프로젝트만: OUTPUT_DIR 유지, 해당 프로젝트 .json만 교체
        os.makedirs(output_dir, exist_ok=True)
        prefix = project.replace(os.path.sep, "_") + "_"
        for f in os.listdir(output_dir):
            if f.startswith(prefix) and f.endswith(".json"):
                os.remove(os.path.join(output_dir, f))
                print(f"[Info] Removed old: {f}")
        data_files = [
            f for f in glob.glob(os.path.join(input_dir, "*.data"))
            if os.path.basename(f).startswith(prefix)
        ]
        print(f"[*] Project mode: {project} ({len(data_files)} .data files)")
    else:
        # 전체 변환: OUTPUT_DIR 초기화
        if os.path.exists(output_dir):
            try:
                shutil.rmtree(output_dir)
                print(f"[Info] Removed existing directory: {output_dir}")
            except Exception as e:
                print(f"[Error] Failed to remove directory: {e}")
                return
        os.makedirs(output_dir)
        print(f"[Info] Created output directory: {output_dir}")
        data_files = glob.glob(os.path.join(input_dir, "*.data"))

    print(f"[*] Found {len(data_files)} files.")
    success_count = 0
    for data_file in data_files:
        filename = os.path.basename(data_file)
        json_filename = filename.replace(".data", ".json")
        output_path = os.path.join(output_dir, json_filename)

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
