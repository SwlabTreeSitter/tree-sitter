#!/usr/bin/env python3
"""
analyze_noise_candidates.py

rank_miss_breakdown_<lang>.csv 에서 Top-10 안에 들어가 정답을 밀어낸
"noise" 후보들을 분석한다.

분석 항목:
  1. noise 후보 빈도 집계 (어떤 후보가 가장 자주 top-10에 등장하나)
  2. noise 후보별 점수 기여 state 집계 (어떤 state가 점수를 부풀리나)
  3. candidates.json 에서 해당 후보의 전체 분포 (몇 개 state, 총 frequency)
  4. LR_Items_Dump.txt 에서 기여도 상위 state의 grammar items 확인

사용법:
  python3 analyze_noise_candidates.py ruby
  python3 analyze_noise_candidates.py ruby --top 10
"""

import sys
import os
import re
import csv
import json
from collections import Counter, defaultdict

REPORT_BASE = "/home/hyeonjin/PL/tree-sitter/reports"

LANG_CONFIGS = {
    "ruby": {
        "candidates": "/home/hyeonjin/PL/code-completion-extension/resources/ruby/candidates.json",
        "lr_dump":    "/home/hyeonjin/PL/tree-sitter-ruby/LR_Items_Dump.txt",
    },
    "haskell": {
        "candidates": "/home/hyeonjin/PL/code-completion-extension/resources/haskell/candidates.json",
        "lr_dump":    "/home/hyeonjin/PL/tree-sitter-haskell/LR_Items_Dump.txt",
    },
    "php": {
        "candidates": "/home/hyeonjin/PL/code-completion-extension/resources/php/candidates.json",
        "lr_dump":    "/home/hyeonjin/PL/tree-sitter-php/php/LR_Items_Dump.txt",
    },
    "javascript": {
        "candidates": "/home/hyeonjin/PL/code-completion-extension/resources/javascript/candidates.json",
        "lr_dump":    "/home/hyeonjin/PL/tree-sitter-javascript/LR_Items_Dump.txt",
    },
    "cpp": {
        "candidates": "/home/hyeonjin/PL/code-completion-extension/resources/cpp/candidates.json",
        "lr_dump":    "/home/hyeonjin/PL/tree-sitter-cpp/LR_Items_Dump.txt",
    },
    "java": {
        "candidates": "/home/hyeonjin/PL/code-completion-extension/resources/java/candidates.json",
        "lr_dump":    "/home/hyeonjin/PL/tree-sitter-java/LR_Items_Dump.txt",
    },
    "python": {
        "candidates": "/home/hyeonjin/PL/code-completion-extension/resources/python/candidates.json",
        "lr_dump":    "/home/hyeonjin/PL/tree-sitter-python/LR_Items_Dump.txt",
    },
}

TOP_N = [15]  # 상위 몇 개 noise 후보를 분석할지 (mutable container for CLI override)
TOP_STATES = 5  # 후보당 상위 몇 개 state를 표시할지


def parse_breakdown(breakdown_str):
    """Top10_Breakdown 문자열을 파싱.
    Returns: [(rank, name, total_score, [(state_id, score), ...]), ...]
    """
    candidates = []
    if not breakdown_str:
        return candidates

    parts = breakdown_str.split(" | ")
    for part in parts:
        part = part.strip()
        m = re.match(r'R(\d+)\s+(.+?)=(\d+)\(([^)]*)\)(.*)', part)
        if not m:
            continue

        rank = int(m.group(1))
        name = m.group(2).strip()
        total_score = int(m.group(3))
        state_str = m.group(4)
        is_gt = "[GT]" in m.group(5)

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
            "is_gt": is_gt,
        })

    return candidates


def load_breakdown(lang):
    """rank_miss_breakdown CSV 로드."""
    path = os.path.join(REPORT_BASE, lang, f"rank_miss_breakdown_{lang}.csv")
    if not os.path.exists(path):
        print(f"  [{lang}] breakdown CSV not found: {path}")
        return []

    cases = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            candidates = parse_breakdown(row.get("Top10_Breakdown", ""))
            cases.append({
                "file": row["File"],
                "loc": row["Location"],
                "gt": row["Ground_Truth"],
                "final_rank": int(row["Final_Rank"]),
                "candidates": candidates,
            })
    return cases


def load_candidates_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_lr_dump_state(lr_dump_path, target_state_id):
    """LR_Items_Dump.txt 에서 특정 state의 items 추출."""
    if not os.path.exists(lr_dump_path):
        return None

    target_header = f"State {target_state_id}:"
    lines = []
    found = False

    with open(lr_dump_path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line == target_header:
                found = True
                continue
            if found:
                if line.startswith("State ") and line.endswith(":"):
                    break
                lines.append(line)

    return lines if found else None


# =============================================================
# Analysis 1: Noise 후보 빈도 집계
# =============================================================

def analysis_1_frequency(cases):
    """top-10에 가장 자주 등장하는 noise 후보 집계."""
    cand_count = Counter()       # 후보가 top-10에 등장한 케이스 수
    cand_total_score = Counter() # 후보의 누적 점수

    for case in cases:
        for c in case["candidates"]:
            if c["rank"] <= 10 and not c["is_gt"]:
                cand_count[c["name"]] += 1
                cand_total_score[c["name"]] += c["score"]

    print(f"\n{'='*70}")
    print(f"  [1] Noise 후보 빈도 (top-10에 가장 자주 등장)")
    print(f"{'='*70}")
    print(f"  총 rank miss 케이스: {len(cases)}")
    print(f"\n  {'후보':<45} {'등장 횟수':>10} {'누적 점수':>14}")
    print(f"  {'-'*69}")

    top_noise = cand_count.most_common(TOP_N[0])
    for name, count in top_noise:
        pct = count / len(cases) * 100
        print(f"  {name:<45} {count:>7} ({pct:>5.1f}%) {cand_total_score[name]:>14,}")

    return [name for name, _ in top_noise]


# =============================================================
# Analysis 2: Noise 후보별 state 기여도
# =============================================================

def analysis_2_state_contribution(cases, top_noise):
    """각 noise 후보를 top-10으로 밀어올린 state별 점수 기여도."""
    # noise_name -> state_id -> (total_score, count)
    state_contrib = defaultdict(lambda: defaultdict(lambda: [0, 0]))

    for case in cases:
        for c in case["candidates"]:
            if c["rank"] <= 10 and not c["is_gt"] and c["name"] in top_noise:
                for state_id, score in c["states"]:
                    state_contrib[c["name"]][state_id][0] += score
                    state_contrib[c["name"]][state_id][1] += 1

    print(f"\n{'='*70}")
    print(f"  [2] Noise 후보별 점수 기여 state (상위 {TOP_STATES}개)")
    print(f"{'='*70}")

    # 반환: {noise_name: [(state_id, total_score, count), ...]}
    top_states_per_noise = {}

    for name in top_noise:
        if name not in state_contrib:
            continue
        sorted_states = sorted(
            state_contrib[name].items(),
            key=lambda x: x[1][0], reverse=True
        )[:TOP_STATES]

        total_all = sum(v[0] for v in state_contrib[name].values())

        print(f"\n  [{name}] (총 {len(state_contrib[name])}개 state, 누적 점수: {total_all:,})")
        print(f"    {'State':>8}  {'누적 점수':>14}  {'비율':>7}  {'등장 횟수':>10}")
        print(f"    {'-'*45}")

        top_states_per_noise[name] = []
        for state_id, (score, count) in sorted_states:
            pct = score / total_all * 100 if total_all > 0 else 0
            print(f"    {state_id:>8}  {score:>14,}  {pct:>6.1f}%  {count:>10}")
            top_states_per_noise[name].append((state_id, score, count))

    return top_states_per_noise


# =============================================================
# Analysis 3: candidates.json 전체 분포
# =============================================================

def analysis_3_db_distribution(db, top_noise):
    """candidates.json 에서 noise 후보가 몇 개 state에 분포하는지."""
    # noise_name -> [(state_id, frequency), ...]
    dist = defaultdict(list)

    for state_id_str, entries in db.items():
        for entry in entries:
            if entry["key"] in top_noise:
                dist[entry["key"]].append((int(state_id_str), entry["value"]))

    print(f"\n{'='*70}")
    print(f"  [3] candidates.json 전체 분포")
    print(f"{'='*70}")
    print(f"\n  {'후보':<45} {'state 수':>9} {'총 frequency':>14} {'최대 frequency':>14}")
    print(f"  {'-'*82}")

    for name in top_noise:
        entries = dist.get(name, [])
        if not entries:
            print(f"  {name:<45} {'N/A':>9}")
            continue
        total_freq = sum(f for _, f in entries)
        max_freq = max(f for _, f in entries)
        max_state = [s for s, f in entries if f == max_freq][0]
        print(f"  {name:<45} {len(entries):>9} {total_freq:>14,} {max_freq:>14,} (s{max_state})")


# =============================================================
# Analysis 4: LR_Items_Dump 대조
# =============================================================

def analysis_4_lr_verification(lr_dump_path, top_states_per_noise, top_noise):
    """기여도 상위 state의 LR items에서 해당 후보가 실제로 존재하는지 확인."""
    if not os.path.exists(lr_dump_path):
        print(f"\n  [4] LR_Items_Dump not found: {lr_dump_path}")
        return

    # 검사할 (state, noise_name) 쌍 수집
    pairs_to_check = set()
    for name in top_noise:
        if name not in top_states_per_noise:
            continue
        for state_id, _, _ in top_states_per_noise[name]:
            pairs_to_check.add((state_id, name))

    # 필요한 state들의 items 로드
    needed_states = set(s for s, _ in pairs_to_check)
    state_items = {}
    for sid in needed_states:
        items = load_lr_dump_state(lr_dump_path, sid)
        if items:
            state_items[sid] = items

    print(f"\n{'='*70}")
    print(f"  [4] LR_Items_Dump 대조 검증")
    print(f"{'='*70}")

    for name in top_noise:
        if name not in top_states_per_noise:
            continue

        print(f"\n  [{name}]")

        for state_id, score, count in top_states_per_noise[name]:
            items = state_items.get(state_id, [])
            if not items:
                print(f"    State {state_id}: (items not found)")
                continue

            # name의 첫 번째 symbol이 • 뒤에 나타나는 item 찾기
            first_sym = name.split()[0]
            matching_items = []
            for item_line in items:
                item_line_stripped = item_line.strip()
                if not item_line_stripped or item_line_stripped.startswith("("):
                    continue
                # "rule → ... • first_sym ..." 패턴 검색
                if f"• {first_sym}" in item_line_stripped:
                    matching_items.append(item_line_stripped)
                # 완전 매치도 검색: "• name" (multi-word)
                if len(name.split()) > 1 and f"• {name}" in item_line_stripped:
                    matching_items.append(item_line_stripped)

            status = "OK" if matching_items else "NOT_FOUND"
            print(f"    State {state_id} (score={score:,}, count={count}): [{status}]")
            if matching_items:
                for mi in matching_items[:3]:
                    print(f"      {mi}")
                if len(matching_items) > 3:
                    print(f"      ... ({len(matching_items)} items total)")
            else:
                # item이 없으면 해당 state의 처음 몇 줄 표시
                print(f"      State {state_id}의 items (처음 5개):")
                shown = 0
                for item_line in items:
                    if item_line.strip() and not item_line.strip().startswith("("):
                        print(f"        {item_line.strip()}")
                        shown += 1
                        if shown >= 5:
                            break


# =============================================================
# main
# =============================================================

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    top_n_arg = TOP_N[0]
    for i, a in enumerate(sys.argv[1:]):
        if a == "--top" and i + 2 < len(sys.argv):
            top_n_arg = int(sys.argv[i + 2])

    if not args:
        print(f"Usage: python3 analyze_noise_candidates.py <language> [--top N]")
        print(f"Available: {', '.join(LANG_CONFIGS.keys())}")
        sys.exit(1)

    lang = args[0].lower()
    if lang not in LANG_CONFIGS:
        print(f"Unknown language: {lang}")
        sys.exit(1)

    TOP_N[0] = top_n_arg

    cfg = LANG_CONFIGS[lang]

    print(f"\n[*] Language: {lang}")
    print(f"[*] Loading rank_miss_breakdown...")
    cases = load_breakdown(lang)
    if not cases:
        print("No data.")
        return

    print(f"[*] Loaded {len(cases)} rank miss cases.")

    # Analysis 1
    top_noise = analysis_1_frequency(cases)
    top_noise_set = set(top_noise)

    # Analysis 2
    top_states = analysis_2_state_contribution(cases, top_noise_set)

    # Analysis 3
    print(f"\n[*] Loading candidates.json...")
    db = load_candidates_json(cfg["candidates"])
    analysis_3_db_distribution(db, top_noise)

    # Analysis 4
    print(f"\n[*] Loading LR_Items_Dump...")
    analysis_4_lr_verification(cfg["lr_dump"], top_states, top_noise)

    print(f"\n[*] Done.")


if __name__ == "__main__":
    main()
