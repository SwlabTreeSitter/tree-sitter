"""
generate_not_found_breakdown.py

언어별 debug_coverage_<lang>/*.csv 와 reports/<lang>/*.json 을 읽어
NOT_FOUND 케이스를 Data Shortage / Conversion Error 로 분류한 뒤
reports/not_found_breakdown.md 로 출력한다.

분류 기준:
  - LR Items (LR_Items_Dump.txt) 에서 state_id -> 가능한 suffix 집합을 빌드
  - NOT_FOUND 커서 위치의 정답 후보 전체(JSON)를 state_list 의 LR items 와 매칭
  - 하나라도 매칭 → Data Shortage (상태는 맞지만 DB에 학습 데이터 없음)
  - 전혀 매칭 안됨 → Conversion Error (컨버전이 잘못된 상태를 반환함)
"""

import os
import re
import csv
import ast
import json
from collections import defaultdict, Counter

LANG_CONFIGS = {
    "c": {
        "lr_items": "/home/hyeonjin/PL/tree-sitter-c/LR_Items_Dump.txt",
        "debug_dir": "/home/hyeonjin/PL/tree-sitter/reports/c11/debug_coverage_c",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/c11",
    },
    "haskell": {
        "lr_items": "/home/hyeonjin/PL/tree-sitter-haskell/LR_Items_Dump.txt",
        "debug_dir": "/home/hyeonjin/PL/tree-sitter/reports/haskell/debug_coverage_haskell",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/haskell",
    },
    "ruby": {
        "lr_items": "/home/hyeonjin/PL/tree-sitter-ruby/LR_Items_Dump.txt",
        "debug_dir": "/home/hyeonjin/PL/tree-sitter/reports/ruby/debug_coverage_ruby",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/ruby",
    },
    "php": {
        "lr_items": "/home/hyeonjin/PL/tree-sitter-php/php/LR_Items_Dump.txt",
        "debug_dir": "/home/hyeonjin/PL/tree-sitter/reports/php/debug_coverage_php",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/php",
    },
    "javascript": {
        "lr_items": "/home/hyeonjin/PL/tree-sitter-javascript/LR_Items_Dump.txt",
        "debug_dir": "/home/hyeonjin/PL/tree-sitter/reports/javascript/debug_coverage_javascript",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/javascript",
    },
    "cpp": {
        "lr_items": "/home/hyeonjin/PL/tree-sitter-cpp/LR_Items_Dump.txt",
        "debug_dir": "/home/hyeonjin/PL/tree-sitter/reports/cpp/debug_coverage_cpp",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/cpp",
    },
    "java": {
        "lr_items": "/home/hyeonjin/PL/tree-sitter-java/LR_Items_Dump.txt",
        "debug_dir": "/home/hyeonjin/PL/tree-sitter/reports/java/debug_coverage_java",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/java",
    },
    "python": {
        "lr_items": "/home/hyeonjin/PL/tree-sitter-python/LR_Items_Dump.txt",
        "debug_dir": "/home/hyeonjin/PL/tree-sitter/reports/python/debug_coverage_python",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/python",
    },
}

OUTPUT_SUMMARY = "/home/hyeonjin/PL/tree-sitter/reports/not_found_summary.csv"
OUTPUT_DETAIL  = "/home/hyeonjin/PL/tree-sitter/reports/not_found_detail.csv"
LANG_ORDER     = ["c", "haskell", "ruby", "php", "javascript", "cpp", "java", "python"]


def build_lr_index(lr_path):
    """state_id -> set of suffixes after • (lookahead 제외)."""
    state_suffixes = defaultdict(set)
    current_state = None
    with open(lr_path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r'^State (\d+):', line)
            if m:
                current_state = int(m.group(1))
            elif current_state is not None and '•' in line:
                after = line.split('•', 1)[1].split('[Lookahead')[0].strip()
                if after:
                    state_suffixes[current_state].add(after)
    return state_suffixes


def is_in_lr(state_suffixes, states, candidates):
    """candidates 중 하나라도 states 의 LR items 에 존재하면 True."""
    for sid in states:
        suffixes = state_suffixes.get(sid, set())
        for gt in candidates:
            if gt in suffixes:
                return True
    return False


def first_matched_candidate(state_suffixes, states, candidates):
    """매칭된 첫 번째 candidate 반환 (데이터 부족 레이블용)."""
    for gt in candidates:
        for sid in states:
            if gt in state_suffixes.get(sid, set()):
                return gt
    return candidates[0]


def analyze_lang(cfg):
    print(f"  Building LR index: {cfg['lr_items']}")
    state_suffixes = build_lr_index(cfg["lr_items"])

    shortage = Counter()
    conv_err = Counter()

    for fname in sorted(os.listdir(cfg["debug_dir"])):
        if not fname.endswith(".csv"):
            continue
        csv_path  = os.path.join(cfg["debug_dir"], fname)
        json_path = os.path.join(cfg["json_dir"], fname.replace(".csv", ".json"))

        gt_map = {}
        if os.path.exists(json_path):
            with open(json_path, encoding="utf-8") as f:
                jdata = json.load(f)
            for loc_key, entries in jdata.items():
                gt_map[loc_key] = [e["candidate"] for e in entries]

        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["Coverage_Result"] != "NOT_FOUND":
                    continue
                loc     = row["Location"].strip('"')
                csv_gt  = row["Ground_Truth"].strip()
                try:
                    states = ast.literal_eval(row["State_List"])
                except Exception:
                    continue

                candidates = gt_map.get(loc, [csv_gt])

                if is_in_lr(state_suffixes, states, candidates):
                    matched = first_matched_candidate(state_suffixes, states, candidates)
                    shortage[matched] += 1
                else:
                    conv_err[csv_gt] += 1

    return shortage, conv_err


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
            s, c = results[lang]
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
        writer.writerow(["Language", "Category", "Ground_Truth", "Count"])
        for lang in LANG_ORDER:
            shortage, conv_err = results[lang]
            for gt, cnt in shortage.most_common():
                writer.writerow([lang, "Data_Shortage", gt, cnt])
            for gt, cnt in conv_err.most_common():
                writer.writerow([lang, "Conv_Error", gt, cnt])


def main():
    results = {}
    for lang in LANG_ORDER:
        print(f"[{lang}]")
        cfg = LANG_CONFIGS[lang]
        shortage, conv_err = analyze_lang(cfg)
        results[lang] = (shortage, conv_err)
        ts, tc = sum(shortage.values()), sum(conv_err.values())
        print(f"  shortage={ts}, conv_err={tc}, total={ts+tc}")

    write_reports(results)
    print(f"\n[Saved] {OUTPUT_SUMMARY}")
    print(f"[Saved] {OUTPUT_DETAIL}")


if __name__ == "__main__":
    main()
