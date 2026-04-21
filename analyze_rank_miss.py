#!/usr/bin/env python3
"""
analyze_rank_miss.py

debug_coverage_<lang>/*.csv 와 candidates.json 을 읽어
정답이 Top-10 밖으로 밀려난 케이스를 분석한다.

출력:
  1. reports/<lang>/rank_miss_breakdown_<lang>.csv     (전체 케이스 state별 점수 분해)
  2. reports/<lang>/rank_miss_examples/                (rank=11,12,13 stacked bar chart)
  3. reports/<lang>/rank_miss_aggregate_<lang>.png     (전체 케이스 집계 시각화)
  4. reports/rank_miss_summary.csv                     (언어별 요약)

사용법:
  python3 analyze_rank_miss.py                         # 전체 언어
  python3 analyze_rank_miss.py haskell java             # 특정 언어만
  python3 analyze_rank_miss.py --threshold 20 java      # Top-20 밖 기준
"""

import sys
import os
import csv
import ast
import json
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.cm as cm

REPORT_BASE = "/home/hyeonjin/PL/tree-sitter/reports"

LANG_CONFIGS = {
    "haskell":    "/home/hyeonjin/PL/code-completion-extension/resources/haskell/candidates.json",
    "ruby":       "/home/hyeonjin/PL/code-completion-extension/resources/ruby/candidates.json",
    "php":        "/home/hyeonjin/PL/code-completion-extension/resources/php/candidates.json",
    "javascript": "/home/hyeonjin/PL/code-completion-extension/resources/javascript/candidates.json",
    "cpp":        "/home/hyeonjin/PL/code-completion-extension/resources/cpp/candidates.json",
    "java":       "/home/hyeonjin/PL/code-completion-extension/resources/java/candidates.json",
    "python":     "/home/hyeonjin/PL/code-completion-extension/resources/python/candidates.json",
    "c":          "/home/hyeonjin/PL/code-completion-extension/resources/c/candidates.json",
    "smallbasic": "/home/hyeonjin/PL/code-completion-extension/resources/smallbasic/candidates.json",
}

DEFAULT_THRESHOLD = 10
EXAMPLE_RANKS = {11, 12, 13}
MAX_CANDIDATES_IN_CHART = 20  # 그래프에 표시할 최대 후보 수


def load_db(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def merge_with_breakdown(db, states):
    """state별 점수를 분리하여 반환.
    Returns:
        merged_total: dict[candidate] -> total_score
        per_state: dict[candidate] -> dict[state_id] -> score
    """
    merged_total = defaultdict(int)
    per_state = defaultdict(lambda: defaultdict(int))

    for state in states:
        s_key = str(state)
        if s_key not in db:
            continue
        for item in db[s_key]:
            key = item["key"]
            val = item["value"]
            merged_total[key] += val
            per_state[key][state] += val

    return merged_total, per_state


def get_final_rank(merged_total, ground_truth):
    """병합 결과에서 정답의 순위와 점수."""
    sorted_cands = sorted(merged_total.items(), key=lambda x: x[1], reverse=True)
    gt_clean = ground_truth.replace(" ", "")
    for rank, (key, score) in enumerate(sorted_cands, 1):
        if key.replace(" ", "") == gt_clean:
            return rank, score, sorted_cands
    return 0, 0, sorted_cands


# ============================================================
# 1. 상세 CSV: 전체 케이스의 state별 점수 분해
# ============================================================

def analyze_and_save_breakdown(lang, db, threshold):
    """rank > threshold인 모든 케이스를 분석하여 breakdown CSV 저장."""
    debug_dir = os.path.join(REPORT_BASE, lang, f"debug_coverage_{lang}")
    if not os.path.isdir(debug_dir):
        print(f"  [{lang}] debug dir not found: {debug_dir}")
        return [], {}

    all_cases = []   # 시각화/집계용 데이터
    csv_rows = []    # CSV 기록용
    summary_stats = defaultdict(int)
    rank_sum = 0
    max_rank = 0

    for fname in sorted(os.listdir(debug_dir)):
        if not fname.endswith(".csv"):
            continue
        src_name = fname[:-4]

        with open(os.path.join(debug_dir, fname), encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rank = int(row.get("Rank", "0"))
                if rank == 0 or rank <= threshold:
                    continue

                gt = row["Ground_Truth"].strip()
                try:
                    states = ast.literal_eval(row.get("State_List", ""))
                except Exception:
                    continue

                loc = row["Location"].strip('"')

                # 병합 + state별 분해
                merged_total, per_state = merge_with_breakdown(db, states)
                final_rank, final_score, sorted_cands = get_final_rank(merged_total, gt)

                # state별 정답 존재 여부
                gt_clean = gt.replace(" ", "")
                gt_present_states = []
                gt_absent_states = []
                for st in states:
                    found_in_state = False
                    for cand, st_scores in per_state.items():
                        if cand.replace(" ", "") == gt_clean and st in st_scores:
                            found_in_state = True
                            break
                    if found_in_state:
                        gt_present_states.append(st)
                    else:
                        gt_absent_states.append(st)

                # 상위 후보들의 state별 점수 분해 문자열
                top_breakdown = []
                for cand, total_score in sorted_cands[:10]:
                    state_parts = []
                    for st in states:
                        s = per_state[cand].get(st, 0)
                        if s > 0:
                            state_parts.append(f"s{st}:{s}")
                    is_gt = " [GT]" if cand.replace(" ", "") == gt_clean else ""
                    top_breakdown.append(f"R{len(top_breakdown)+1} {cand}={total_score}({'+'.join(state_parts)}){is_gt}")

                rank_sum += final_rank
                if final_rank > max_rank:
                    max_rank = final_rank
                summary_stats["total"] += 1

                csv_rows.append({
                    "File":              src_name,
                    "Location":          loc,
                    "Ground_Truth":      gt,
                    "Final_Rank":        final_rank,
                    "Final_Score":       final_score,
                    "States_Count":      len(states),
                    "GT_Present_States": len(gt_present_states),
                    "GT_Absent_States":  len(gt_absent_states),
                    "Top10_Breakdown":   " | ".join(top_breakdown),
                })

                # 시각화/집계용 데이터 보존
                all_cases.append({
                    "file": src_name,
                    "loc": loc,
                    "gt": gt,
                    "final_rank": final_rank,
                    "final_score": final_score,
                    "states": states,
                    "sorted_cands": sorted_cands,
                    "per_state": per_state,
                    "gt_present": len(gt_present_states),
                    "gt_absent": len(gt_absent_states),
                })

    # CSV 저장
    out_dir = os.path.join(REPORT_BASE, lang)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"rank_miss_breakdown_{lang}.csv")
    if csv_rows:
        fieldnames = list(csv_rows[0].keys())
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(csv_rows)
        print(f"  [{lang}] Breakdown CSV: {out_path} ({len(csv_rows)} cases)")

    total = summary_stats["total"]
    summary = {
        "Language":       lang,
        "Total_Miss":     total,
        "Avg_Final_Rank": round(rank_sum / total, 1) if total > 0 else 0,
        "Max_Final_Rank": max_rank,
    }

    return all_cases, summary


# ============================================================
# 2. 개별 그래프: rank=11,12,13 stacked bar chart
# ============================================================

def plot_examples(lang, all_cases):
    """rank=11,12,13인 케이스를 stacked bar chart로 시각화."""
    examples = [c for c in all_cases if c["final_rank"] in EXAMPLE_RANKS]
    if not examples:
        print(f"  [{lang}] No rank=11,12,13 cases found.")
        return

    out_dir = os.path.join(REPORT_BASE, lang, "rank_miss_examples")
    os.makedirs(out_dir, exist_ok=True)

    count = 0
    for case in examples:
        if count >= 50:  # 언어당 최대 50개
            break

        states = case["states"]
        sorted_cands = case["sorted_cands"]
        per_state = case["per_state"]
        gt = case["gt"]
        gt_clean = gt.replace(" ", "")

        # 상위 N개 후보만 표시
        display_cands = sorted_cands[:MAX_CANDIDATES_IN_CHART]
        cand_names = [c[0] for c in display_cands]
        cand_totals = [c[1] for c in display_cands]

        # 색상 팔레트 (state별)
        colors = cm.tab20.colors
        state_list = list(states)

        fig, ax = plt.subplots(figsize=(16, max(6, len(cand_names) * 0.4)))

        # 가로 stacked bar
        bottoms = [0] * len(cand_names)
        for si, st in enumerate(state_list):
            values = [per_state[cand].get(st, 0) for cand in cand_names]
            color = colors[si % len(colors)]
            ax.barh(cand_names, values, left=bottoms, color=color,
                    label=f"state {st}", edgecolor="white", linewidth=0.3)
            bottoms = [b + v for b, v in zip(bottoms, values)]

        # 정답 후보 강조
        for i, name in enumerate(cand_names):
            if name.replace(" ", "") == gt_clean:
                ax.barh([name], [0], color="none", edgecolor="red", linewidth=2.5)
                ax.text(bottoms[i] + 1, i, f" [GT] rank={case['final_rank']}",
                        va="center", fontsize=9, color="red", fontweight="bold")

        ax.set_xlabel("Score", fontsize=11)
        ax.set_title(
            f"[{lang}] {case['file']}@{case['loc']}\n"
            f"GT=\"{gt}\"  rank={case['final_rank']}  "
            f"states={len(states)}(present={case['gt_present']}, absent={case['gt_absent']})",
            fontsize=10
        )
        ax.invert_yaxis()

        # 범례 (그래프 외부 배치)
        ncol = max(1, len(state_list) // 10 + 1)
        ax.legend(fontsize=6, loc="upper left", bbox_to_anchor=(1.01, 1.0), ncol=ncol, borderaxespad=0)

        fig.subplots_adjust(right=0.75)
        safe_name = f"rank{case['final_rank']}_{case['file']}_{case['loc']}"
        safe_name = safe_name.replace("/", "_")[:140] + ".png"
        out_path = os.path.join(out_dir, safe_name)
        plt.savefig(out_path, dpi=120)
        plt.close()
        count += 1

    print(f"  [{lang}] Example charts: {out_dir} ({count} files)")


# ============================================================
# 3. 집계 시각화: 전체 케이스 통계
# ============================================================

def plot_aggregate(lang, all_cases):
    """전체 rank > threshold 케이스의 집계 시각화."""
    if not all_cases:
        return

    out_dir = os.path.join(REPORT_BASE, lang)

    # --- 3a. 정답의 state 존재 비율 분포 ---
    presence_ratios = []
    for c in all_cases:
        total_states = c["gt_present"] + c["gt_absent"]
        if total_states > 0:
            presence_ratios.append(c["gt_present"] / total_states)

    # --- 3b. 정답을 밀어낸 상위 후보들의 state 기여 집중도 ---
    # 각 케이스에서 rank 1~10 후보가 "몇 개 state에서 점수를 받는가"
    competitor_state_counts = []
    for c in all_cases:
        per_state = c["per_state"]
        for cand, _ in c["sorted_cands"][:10]:
            gt_clean = c["gt"].replace(" ", "")
            if cand.replace(" ", "") == gt_clean:
                continue
            n_contributing = sum(1 for s in c["states"] if per_state[cand].get(s, 0) > 0)
            competitor_state_counts.append(n_contributing)

    # --- 3c. rank 분포 (11~) ---
    rank_dist = defaultdict(int)
    for c in all_cases:
        rank_dist[c["final_rank"]] += 1

    fig, axes = plt.subplots(1, 3, figsize=(18, 5))

    # Plot 1: 정답의 state 존재 비율 분포
    ax = axes[0]
    ax.hist(presence_ratios, bins=20, color="steelblue", edgecolor="white")
    ax.set_xlabel("GT presence ratio (present / total states)", fontsize=10)
    ax.set_ylabel("Cases", fontsize=10)
    ax.set_title(f"[{lang}] GT State Presence Ratio\n(n={len(presence_ratios)})", fontsize=11)
    ax.axvline(x=0.5, color="red", linestyle="--", alpha=0.5, label="50%")
    ax.legend()

    # Plot 2: 상위 후보의 state 기여 수 분포
    ax = axes[1]
    if competitor_state_counts:
        max_sc = max(competitor_state_counts) if competitor_state_counts else 1
        ax.hist(competitor_state_counts, bins=range(1, max_sc + 2),
                color="coral", edgecolor="white", align="left")
    ax.set_xlabel("# states contributing score", fontsize=10)
    ax.set_ylabel("Top-10 competitors", fontsize=10)
    ax.set_title(f"[{lang}] Competitor State Coverage\n(n={len(competitor_state_counts)})", fontsize=11)

    # Plot 3: rank 분포 (11~)
    ax = axes[2]
    ranks_sorted = sorted(rank_dist.keys())
    counts = [rank_dist[r] for r in ranks_sorted]
    ax.bar(ranks_sorted, counts, color="mediumpurple", edgecolor="white")
    ax.set_xlabel("Final Rank", fontsize=10)
    ax.set_ylabel("Cases", fontsize=10)
    ax.set_title(f"[{lang}] Rank Distribution (>{DEFAULT_THRESHOLD})\n(n={len(all_cases)})", fontsize=11)
    if ranks_sorted:
        ax.set_xlim(min(ranks_sorted) - 1, min(max(ranks_sorted) + 1, 100))

    plt.tight_layout()
    out_path = os.path.join(out_dir, f"rank_miss_aggregate_{lang}.png")
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"  [{lang}] Aggregate chart: {out_path}")


# ============================================================
# 4. 요약 CSV
# ============================================================

def save_summary(summaries):
    out_path = os.path.join(REPORT_BASE, "rank_miss_summary.csv")
    fieldnames = ["Language", "Total_Miss", "Avg_Final_Rank", "Max_Final_Rank"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summaries)
    print(f"\n  [Summary] Saved: {out_path}")


def print_summary(summaries):
    print(f"\n{'Language':<12} {'Miss':>7} {'Avg Rank':>9} {'Max':>5}")
    print("-" * 36)
    for s in summaries:
        print(f"{s['Language']:<12} {s['Total_Miss']:>7} {s['Avg_Final_Rank']:>9} {s['Max_Final_Rank']:>5}")


# ============================================================
# main
# ============================================================

def main():
    threshold = DEFAULT_THRESHOLD
    lang_args = []
    skip_next = False
    for arg in sys.argv[1:]:
        if skip_next:
            threshold = int(arg)
            skip_next = False
            continue
        if arg == "--threshold":
            skip_next = True
            continue
        lang_args.append(arg)

    languages = lang_args if lang_args else list(LANG_CONFIGS.keys())

    summaries = []
    for lang in languages:
        if lang not in LANG_CONFIGS:
            print(f"  [{lang}] Unknown language, skipping.")
            continue

        print(f"\n  [{lang}] Loading DB...")
        db = load_db(LANG_CONFIGS[lang])

        print(f"  [{lang}] Analyzing (threshold={threshold})...")
        all_cases, summary = analyze_and_save_breakdown(lang, db, threshold)
        summaries.append(summary)

        print(f"  [{lang}] Plotting examples (rank=11,12,13)...")
        plot_examples(lang, all_cases)

        print(f"  [{lang}] Plotting aggregate...")
        plot_aggregate(lang, all_cases)

    save_summary(summaries)
    print_summary(summaries)


if __name__ == "__main__":
    main()
