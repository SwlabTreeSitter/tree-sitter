"""
diagnose_conv_errors.py

Conv_Error 케이스를 분류하여 원인을 진단한다.

카테고리:
  A: Reduce-Only State — expected state가 reduce-only → 컬렉션 running_state stuck
  B: Truncation Divergence — 잘린 소스의 파싱이 근본적으로 다름 (state 0 포함 등)
  C: Other — 위에 해당 안 됨

사용법:
  python3 diagnose_conv_errors.py [언어]
  python3 diagnose_conv_errors.py          # 기본: cpp
  python3 diagnose_conv_errors.py java
"""

import os
import csv
import ast
import json
import re
import sys
from collections import Counter, defaultdict

# ============================================================
# 설정
# ============================================================
LANG_CONFIGS = {
    "cpp": {
        "debug_dir": "/home/hyeonjin/PL/tree-sitter/reports/cpp/debug_coverage_cpp",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/cpp",
        "action_table": "/home/hyeonjin/PL/tree-sitter-cpp/saved_action_table.txt",
    },
    "java": {
        "debug_dir": "/home/hyeonjin/PL/tree-sitter/reports/java/debug_coverage_java",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/java",
        "action_table": "/home/hyeonjin/PL/tree-sitter-java/saved_action_table.txt",
    },
}

OUTPUT_CSV = "/home/hyeonjin/PL/tree-sitter/reports/conv_error_diagnosis.csv"


# ============================================================
# 1. Action Table 로드
# ============================================================
def load_action_table(path):
    """action table을 읽어 state별 액션 목록을 반환한다.
    Returns: {state_id: [(symbol, action_type_string), ...]}
    """
    table = defaultdict(list)
    if not os.path.exists(path):
        print(f"[WARN] Action table not found: {path}")
        return table
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            try:
                state_id = int(parts[0])
            except ValueError:
                continue
            symbol = parts[1]
            action = parts[2]
            table[state_id].append((symbol, action))
    return table


# ============================================================
# 2. Reduce-Only 집합 구축
# ============================================================
def build_reduce_only_set(action_table):
    """Shift 액션이 없는 상태들의 집합을 반환한다 (ShiftExtra 제외)."""
    reduce_only = set()
    for state_id, actions in action_table.items():
        has_real_shift = False
        for symbol, action in actions:
            if action.startswith("Shift") and action != "ShiftExtra":
                has_real_shift = True
                break
        if not has_real_shift and len(actions) > 0:
            reduce_only.add(state_id)
    return reduce_only


def get_reduce_info(action_table, state_id):
    """reduce-only 상태의 reduce 대상 (production symbol)을 반환한다."""
    actions = action_table.get(state_id, [])
    for symbol, action in actions:
        if action.startswith("Reduce"):
            # "Reduce preproc_include [prod=37, len=3, dyn_prec=0]"
            m = re.match(r"Reduce (\S+)", action)
            if m:
                return m.group(1)
    return None


# ============================================================
# 3. Conv_Error 케이스 추출
# ============================================================
def extract_conv_errors(debug_dir, json_dir):
    """NOT_FOUND 중 state 교집합이 빈 케이스(Conv_Error)를 추출한다."""
    cases = []
    for fname in sorted(os.listdir(debug_dir)):
        if not fname.endswith(".csv"):
            continue
        csv_path = os.path.join(debug_dir, fname)
        json_path = os.path.join(json_dir, fname.replace(".csv", ".json"))

        gt_map = {}
        if os.path.exists(json_path):
            with open(json_path, encoding="utf-8") as f:
                gt_map = json.load(f)

        src_name = fname[:-4]  # strip .csv

        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["Coverage_Result"] != "NOT_FOUND":
                    continue
                loc = row["Location"].strip('"')
                try:
                    states = ast.literal_eval(row["State_List"])
                except Exception:
                    continue

                gt_entries = gt_map.get(loc, [])
                if not gt_entries:
                    continue

                gt_state_ids = {e["state_id"] for e in gt_entries}
                # Conv_Error: 교집합이 비어있음
                if not (set(states) & gt_state_ids):
                    cases.append({
                        "file": src_name,
                        "location": loc,
                        "ground_truth": row["Ground_Truth"].strip(),
                        "expected_states": sorted(gt_state_ids),
                        "returned_states": states,
                    })
    return cases


# ============================================================
# 4. 분류
# ============================================================
def classify(case, reduce_only_set):
    """케이스를 카테고리로 분류한다."""
    expected = case["expected_states"]
    returned = case["returned_states"]

    # A: expected state가 모두 reduce-only
    all_reduce_only = all(s in reduce_only_set for s in expected)
    if all_reduce_only:
        return "A_Reduce_Only"

    # B: returned states에 0(에러)이 포함
    if 0 in returned:
        return "B_Truncation"

    return "C_Other"


# ============================================================
# 5. 리포트
# ============================================================
def report(cases, action_table, reduce_only_set, lang):
    # 분류 실행
    for c in cases:
        c["category"] = classify(c, reduce_only_set)
        # reduce info 추가
        reduce_targets = []
        for s in c["expected_states"]:
            ri = get_reduce_info(action_table, s)
            if ri:
                reduce_targets.append(f"{s}→{ri}")
        c["reduce_info"] = "; ".join(reduce_targets) if reduce_targets else ""

    # 요약
    cat_counter = Counter(c["category"] for c in cases)
    gt_by_cat = defaultdict(lambda: Counter())
    for c in cases:
        gt_by_cat[c["category"]][c["ground_truth"]] += 1

    print(f"\n{'='*60}")
    print(f"  Conv_Error 진단 결과 [{lang}]  (총 {len(cases)}건)")
    print(f"{'='*60}")
    for cat in sorted(cat_counter.keys()):
        print(f"\n  [{cat}] {cat_counter[cat]}건")
        for gt, cnt in gt_by_cat[cat].most_common():
            print(f"    {gt:40s} {cnt}")

    print(f"\n{'='*60}")

    # CSV 저장
    output_path = OUTPUT_CSV.replace(".csv", f"_{lang}.csv")
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Category", "File", "Location", "Ground_Truth",
            "Expected_States", "Returned_States", "Reduce_Info",
        ])
        for c in sorted(cases, key=lambda x: (x["category"], x["ground_truth"], x["file"])):
            writer.writerow([
                c["category"],
                c["file"],
                c["location"],
                c["ground_truth"],
                c["expected_states"],
                c["returned_states"][:10],  # 처음 10개만
                c["reduce_info"],
            ])

    print(f"\n[Saved] {output_path}")


# ============================================================
# Main
# ============================================================
def main():
    lang = sys.argv[1] if len(sys.argv) > 1 else "cpp"
    if lang not in LANG_CONFIGS:
        print(f"[ERROR] Unknown language: {lang}")
        print(f"  Available: {list(LANG_CONFIGS.keys())}")
        return

    cfg = LANG_CONFIGS[lang]
    print(f"[{lang}] Loading action table...")
    action_table = load_action_table(cfg["action_table"])
    print(f"  States in table: {len(action_table)}")

    reduce_only_set = build_reduce_only_set(action_table)
    print(f"  Reduce-only states: {len(reduce_only_set)}")

    print(f"[{lang}] Extracting Conv_Error cases...")
    cases = extract_conv_errors(cfg["debug_dir"], cfg["json_dir"])
    print(f"  Conv_Error cases: {len(cases)}")

    if not cases:
        print("  No Conv_Error cases found.")
        return

    report(cases, action_table, reduce_only_set, lang)


if __name__ == "__main__":
    main()
