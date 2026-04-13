"""
generate_not_found_breakdown.py

언어별 debug_coverage_<lang>/*.csv 와 reports/<lang>/*.json 을 읽어
NOT_FOUND 케이스를 Data Shortage / Conversion Error 로 분류한 뒤
reports/not_found_summary.csv / not_found_detail.csv 로 출력한다.

분류 기준 (state_id 직접 비교):
  - JSON 의 state_id 집합과 컨버전 State_List 의 교집합으로 판단
  - 교집합 ≠ ∅ → Data Shortage (컨버전이 올바른 상태를 반환했지만 DB에 학습 데이터 없음)
  - 교집합 = ∅  → Conversion Error (컨버전이 잘못된 상태를 반환함)
"""

import os
import csv
import ast
import json
from collections import Counter, defaultdict

LANG_CONFIGS = {
    "smallbasic": {
        "debug_dir": "/home/hyeonjin/PL/tree-sitter/reports/smallbasic/debug_coverage_smallbasic",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/smallbasic",
    },
    "c": {
        "debug_dir": "/home/hyeonjin/PL/tree-sitter/reports/c/debug_coverage_c",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/c",
    },
    "haskell": {
        "debug_dir": "/home/hyeonjin/PL/tree-sitter/reports/haskell/debug_coverage_haskell",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/haskell",
    },
    "ruby": {
        "debug_dir": "/home/hyeonjin/PL/tree-sitter/reports/ruby/debug_coverage_ruby",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/ruby",
    },
    "php": {
        "debug_dir": "/home/hyeonjin/PL/tree-sitter/reports/php/debug_coverage_php",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/php",
    },
    "javascript": {
        "debug_dir": "/home/hyeonjin/PL/tree-sitter/reports/javascript/debug_coverage_javascript",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/javascript",
    },
    "cpp": {
        "debug_dir": "/home/hyeonjin/PL/tree-sitter/reports/cpp/debug_coverage_cpp",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/cpp",
    },
    "java": {
        "debug_dir": "/home/hyeonjin/PL/tree-sitter/reports/java/debug_coverage_java",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/java",
    },
    "python": {
        "debug_dir": "/home/hyeonjin/PL/tree-sitter/reports/python/debug_coverage_python",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/python",
    },
}

OUTPUT_SUMMARY = "/home/hyeonjin/PL/tree-sitter/reports/not_found_summary.csv"
OUTPUT_DETAIL  = "/home/hyeonjin/PL/tree-sitter/reports/not_found_detail.csv"
LANG_ORDER     = ["smallbasic", "c", "haskell", "ruby", "php", "javascript", "cpp", "java", "python"]


def is_data_shortage_by_state(states, gt_entries):
    """State_List 와 JSON state_id 집합의 교집합 여부로 판단."""
    gt_state_ids = {e["state_id"] for e in gt_entries}
    return bool(set(states) & gt_state_ids)


def first_matched_candidate_state(states, gt_entries):
    """[현재 방식] State_List 와 교집합인 state_id 의 candidate 반환."""
    gt_state_ids = {e["state_id"] for e in gt_entries}
    matched_ids = set(states) & gt_state_ids
    for e in gt_entries:
        if e["state_id"] in matched_ids:
            return e["candidate"]
    return gt_entries[0]["candidate"]


def analyze_lang(cfg):
    shortage = Counter()
    conv_err = Counter()
    conv_err_files = defaultdict(set)  # candidate -> 발견된 파일명 집합

    for fname in sorted(os.listdir(cfg["debug_dir"])):
        if not fname.endswith(".csv"):
            continue
        csv_path  = os.path.join(cfg["debug_dir"], fname)
        json_path = os.path.join(cfg["json_dir"], fname.replace(".csv", ".json"))

        # JSON: loc -> entries (state_id + candidate 목록)
        gt_map = {}  # loc -> [{"state_id": ..., "candidate": ...}]
        if os.path.exists(json_path):
            with open(json_path, encoding="utf-8") as f:
                jdata = json.load(f)
            for loc_key, entries in jdata.items():
                gt_map[loc_key] = entries

        # 파일명에서 .csv 확장자 제거하여 소스 파일명으로 사용
        src_name = fname[:-4]  # strip ".csv"

        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["Coverage_Result"] != "NOT_FOUND":
                    continue
                loc    = row["Location"].strip('"')
                csv_gt = row["Ground_Truth"].strip()
                try:
                    states = ast.literal_eval(row["State_List"])
                except Exception:
                    continue

                gt_entries = gt_map.get(loc)

                if gt_entries and is_data_shortage_by_state(states, gt_entries):
                    matched = first_matched_candidate_state(states, gt_entries)
                    shortage[matched] += 1
                else:
                    conv_err[csv_gt] += 1
                    conv_err_files[csv_gt].add(src_name)

    return shortage, conv_err, conv_err_files


def write_reports(results):
    # 요약 CSV
    with open(OUTPUT_SUMMARY, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Language", "Total_NOT_FOUND",
            "Data_Shortage", "Shortage_%",
            "Conv_Error", "Conv_Error_%",
        ])
        for lang in LANG_ORDER:
            s, c, _ = results[lang]
            ts, tc = sum(s.values()), sum(c.values())
            total = ts + tc
            if total == 0:
                writer.writerow([lang, 0, 0, 0.0, 0, 0.0])
            else:
                writer.writerow([
                    lang, total,
                    ts, round(100 * ts / total, 2),
                    tc, round(100 * tc / total, 2),
                ])

    # 상세 CSV
    with open(OUTPUT_DETAIL, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Language", "Category", "Ground_Truth", "Count", "Files"])
        for lang in LANG_ORDER:
            shortage, conv_err, conv_err_files = results[lang]
            for gt, cnt in shortage.most_common():
                writer.writerow([lang, "Data_Shortage", gt, cnt, ""])
            for gt, cnt in conv_err.most_common():
                files_str = "; ".join(sorted(conv_err_files.get(gt, [])))
                writer.writerow([lang, "Conv_Error", gt, cnt, files_str])


def main():
    results = {}
    for lang in LANG_ORDER:
        print(f"[{lang}]")
        cfg = LANG_CONFIGS[lang]
        shortage, conv_err, conv_err_files = analyze_lang(cfg)
        results[lang] = (shortage, conv_err, conv_err_files)
        ts, tc = sum(shortage.values()), sum(conv_err.values())
        print(f"  shortage={ts}, conv_err={tc}, total={ts+tc}")

    write_reports(results)
    print(f"\n[Saved] {OUTPUT_SUMMARY}")
    print(f"[Saved] {OUTPUT_DETAIL}")


if __name__ == "__main__":
    main()
