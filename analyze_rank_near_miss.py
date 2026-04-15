#!/usr/bin/env python3
"""
analyze_rank_near_miss.py

rank_miss_breakdown_<lang>.csv 에서 rank=11,12,13 케이스를 분석하여
정답이 Top-10에서 밀려난 원인을 파악한다.

분석 항목:
  1. 점수 격차 분석 (rank 10 vs 정답)
  2. 정답을 밀어낸 후보 빈도 집계
  3. 정답의 state 존재 비율 분포
  4. 상위 후보 vs 정답의 state 기여 수 비교

사용법:
  python3 analyze_rank_near_miss.py                  # 전체 언어
  python3 analyze_rank_near_miss.py haskell ruby     # 특정 언어만
"""

import sys
import os
import csv
import re
from collections import Counter, defaultdict

REPORT_BASE = "/home/hyeonjin/PL/tree-sitter/reports"
ALL_LANGUAGES = ["haskell", "ruby", "php", "javascript", "cpp", "java", "python"]
TARGET_RANKS = {11, 12, 13}


def parse_breakdown(breakdown_str):
    """Top10_Breakdown 문자열을 파싱하여 후보 리스트 반환.
    Returns: [(rank, name, total_score, state_contributions), ...]
      state_contributions: [(state_id, score), ...]
    """
    candidates = []
    if not breakdown_str:
        return candidates

    parts = breakdown_str.split(" | ")
    for part in parts:
        part = part.strip()
        # "R1 identifier=11993(s61:11993)" or "R11 primitive_type=42(s687:42) [GT]"
        m = re.match(r'R(\d+)\s+(.+?)=(\d+)\(([^)]*)\)(.*)', part)
        if not m:
            continue

        rank = int(m.group(1))
        name = m.group(2).strip()
        total_score = int(m.group(3))
        state_str = m.group(4)
        is_gt = "[GT]" in m.group(5)

        # parse state contributions: "s61:11993+s41:775"
        state_contribs = []
        if state_str:
            for sc in state_str.split("+"):
                sm = re.match(r's(\d+):(\d+)', sc.strip())
                if sm:
                    state_contribs.append((int(sm.group(1)), int(sm.group(2))))

        candidates.append({
            "rank": rank,
            "name": name,
            "score": total_score,
            "states": state_contribs,
            "n_states": len(state_contribs),
            "is_gt": is_gt,
        })

    return candidates


def analyze_lang(lang):
    """한 언어의 rank=11,12,13 케이스 분석."""
    breakdown_path = os.path.join(REPORT_BASE, lang, f"rank_miss_breakdown_{lang}.csv")
    if not os.path.exists(breakdown_path):
        print(f"  [{lang}] breakdown CSV not found")
        return None

    cases = []
    with open(breakdown_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rank = int(row["Final_Rank"])
            if rank not in TARGET_RANKS:
                continue
            candidates = parse_breakdown(row.get("Top10_Breakdown", ""))
            if not candidates:
                continue

            gt_entry = None
            for c in candidates:
                if c["is_gt"]:
                    gt_entry = c
                    break

            cases.append({
                "file": row["File"],
                "loc": row["Location"],
                "gt_name": row["Ground_Truth"],
                "final_rank": rank,
                "final_score": int(row["Final_Score"]),
                "states_count": int(row["States_Count"]),
                "gt_present": int(row["GT_Present_States"]),
                "gt_absent": int(row["GT_Absent_States"]),
                "candidates": candidates,
                "gt_entry": gt_entry,
            })

    if not cases:
        print(f"  [{lang}] No rank=11,12,13 cases")
        return None

    return cases


def analysis_1_score_gap(lang, cases):
    """1. 점수 격차 분석: rank 10 vs 정답."""
    gaps = []
    close_count = 0  # 격차 < 10%

    for case in cases:
        gt_score = case["final_score"]
        # rank 10 찾기
        rank10_score = None
        for c in case["candidates"]:
            if c["rank"] == 10:
                rank10_score = c["score"]
                break

        if rank10_score is not None and gt_score > 0:
            gap = rank10_score - gt_score
            gap_pct = gap / rank10_score * 100 if rank10_score > 0 else 0
            gaps.append({"gap": gap, "gap_pct": gap_pct, "rank10": rank10_score, "gt": gt_score})
            if gap_pct < 10:
                close_count += 1

    if not gaps:
        return

    avg_gap_pct = sum(g["gap_pct"] for g in gaps) / len(gaps)
    median_idx = len(gaps) // 2
    sorted_gaps = sorted(gaps, key=lambda x: x["gap_pct"])

    print(f"\n  [1] 점수 격차 (rank 10 vs 정답)")
    print(f"      분석 대상: {len(gaps)}건")
    print(f"      평균 격차: {avg_gap_pct:.1f}%")
    print(f"      중간값 격차: {sorted_gaps[median_idx]['gap_pct']:.1f}%")
    print(f"      아깝게 밀린 케이스 (격차 < 10%): {close_count}건 ({close_count/len(gaps)*100:.1f}%)")
    print(f"      아깝게 밀린 케이스 (격차 < 5%): {sum(1 for g in gaps if g['gap_pct'] < 5)}건")
    print(f"      큰 격차 (> 50%): {sum(1 for g in gaps if g['gap_pct'] > 50)}건")


def analysis_2_frequent_winners(lang, cases):
    """2. 정답을 밀어낸 후보 빈도 집계."""
    winner_counts = Counter()
    winner_by_rank = defaultdict(Counter)  # rank -> candidate name -> count

    for case in cases:
        for c in case["candidates"]:
            if c["rank"] <= 10 and not c["is_gt"]:
                winner_counts[c["name"]] += 1
                winner_by_rank[c["rank"]][c["name"]] += 1

    print(f"\n  [2] 정답을 밀어낸 후보 (rank 1~10에서 가장 자주 등장)")
    total = len(cases)
    for name, count in winner_counts.most_common(15):
        pct = count / total * 100
        print(f"      {count:>5}건 ({pct:>5.1f}%)  {name}")


def analysis_3_gt_state_presence(lang, cases):
    """3. 정답의 state 존재 비율 분포."""
    ratios = []
    for case in cases:
        total_states = case["gt_present"] + case["gt_absent"]
        if total_states > 0:
            ratios.append(case["gt_present"] / total_states)

    if not ratios:
        return

    buckets = {"0~25%": 0, "25~50%": 0, "50~75%": 0, "75~100%": 0}
    for r in ratios:
        if r < 0.25:
            buckets["0~25%"] += 1
        elif r < 0.5:
            buckets["25~50%"] += 1
        elif r < 0.75:
            buckets["50~75%"] += 1
        else:
            buckets["75~100%"] += 1

    avg = sum(ratios) / len(ratios)
    all_present = sum(1 for r in ratios if r == 1.0)

    print(f"\n  [3] 정답의 state 존재 비율 (GT_Present / Total_States)")
    print(f"      평균: {avg:.1%}")
    print(f"      모든 state에 존재: {all_present}건 ({all_present/len(ratios)*100:.1f}%)")
    for bucket, count in buckets.items():
        print(f"      {bucket}: {count}건 ({count/len(ratios)*100:.1f}%)")


def analysis_4_state_contribution_comparison(lang, cases):
    """4. 상위 후보 vs 정답의 state 기여 수 비교."""
    top_n_states = []  # 상위 후보들의 state 기여 수
    gt_n_states = []   # 정답의 state 기여 수

    for case in cases:
        gt_entry = case["gt_entry"]
        if gt_entry:
            gt_n_states.append(gt_entry["n_states"])

        for c in case["candidates"]:
            if c["rank"] <= 10 and not c["is_gt"]:
                top_n_states.append(c["n_states"])

    if not top_n_states or not gt_n_states:
        return

    avg_top = sum(top_n_states) / len(top_n_states)
    avg_gt = sum(gt_n_states) / len(gt_n_states)

    print(f"\n  [4] state 기여 수 비교")
    print(f"      상위 후보 (rank 1~10) 평균: {avg_top:.1f}개 state에서 점수 받음")
    print(f"      정답 (rank 11~13)     평균: {avg_gt:.1f}개 state에서 점수 받음")

    # 분포
    top_dist = Counter(top_n_states)
    gt_dist = Counter(gt_n_states)

    print(f"      상위 후보 분포: ", end="")
    for k in sorted(top_dist.keys())[:8]:
        print(f"{k}개={top_dist[k]}", end=" ")
    print()
    print(f"      정답 분포:      ", end="")
    for k in sorted(gt_dist.keys())[:8]:
        print(f"{k}개={gt_dist[k]}", end=" ")
    print()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    languages = args if args else ALL_LANGUAGES

    for lang in languages:
        print(f"\n{'='*60}")
        print(f"  [{lang.upper()}] rank=11,12,13 Near-Miss 분석")
        print(f"{'='*60}")

        cases = analyze_lang(lang)
        if not cases:
            continue

        print(f"  총 {len(cases)}건 (rank=11: {sum(1 for c in cases if c['final_rank']==11)}, "
              f"rank=12: {sum(1 for c in cases if c['final_rank']==12)}, "
              f"rank=13: {sum(1 for c in cases if c['final_rank']==13)})")

        analysis_1_score_gap(lang, cases)
        analysis_2_frequent_winners(lang, cases)
        analysis_3_gt_state_presence(lang, cases)
        analysis_4_state_contribution_comparison(lang, cases)


if __name__ == "__main__":
    main()
