#!/usr/bin/env python3
"""
verify_lr_candidates.py

rank_miss_breakdown_<lang>.csv 의 각 (state, candidate) 쌍이
LR_Items_Dump.txt 에서 실제로 확인되는 구조후보인지 검증한다.

출력:
  1. reports/<lang>/lr_verification_<lang>.csv   (전체 검증 결과)
  2. reports/<lang>/lr_verification_summary.txt   (요약 통계)

사용법:
  python3 verify_lr_candidates.py ruby
  python3 verify_lr_candidates.py ruby --rank 11 13   # rank 11~13만
"""

import sys
import os
import re
import csv
import json
from collections import defaultdict, Counter

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


# ===========================================================
# LR_Items_Dump 파싱
# ===========================================================

# precedence/associativity annotation:
#   • ( Left ) symbol ...
#   • ( Right ) symbol ...
#   • ( ) symbol ...
#   • ( 3 Left ) symbol ...
#   • ( nonereserved: 18446744073709551615 ) symbol ...
PREC_PATTERN = re.compile(
    r'\(\s*'
    r'(?:'
    r'(?:Left|Right)'                       # Left / Right
    r'|\d+(?:\s+(?:Left|Right))?'           # 3  or  3 Left
    r'|none'                                 # none
    r'|'                                     # empty ()
    r'|[^)]*?reserved:\s*\d+'               # nonereserved: 18446...
    r')'
    r'\s*\)'
)

# alias: identifier_suffix@identifier  -> runtime name is "identifier"
ALIAS_PATTERN = re.compile(r'(\S+)@(\S+)')


def strip_precedence(text):
    """precedence/associativity 주석을 제거."""
    return PREC_PATTERN.sub('', text).strip()


def normalize_after_dot(text):
    """• 뒤의 텍스트를 정규화하여 후보 비교용 문자열 리스트 반환.

    alias가 있는 경우 원본과 alias 모두 포함.
    예: "identifier@hash_key_symbol : foo" → ["hash_key_symbol : foo", "identifier : foo"]
    """
    # 1. precedence 제거
    text = strip_precedence(text)
    text = ' '.join(text.split())

    # 2. alias 처리: 원본 이름과 alias 이름 둘 다 생성
    # variant 1: alias만 (기존 동작)
    variant_alias = ALIAS_PATTERN.sub(r'\2', text)
    # variant 2: 원본만
    variant_orig = ALIAS_PATTERN.sub(r'\1', text)

    results = set()
    if variant_alias:
        results.add(variant_alias)
    if variant_orig:
        results.add(variant_orig)
    if not results and text.strip():
        results.add(text.strip())

    return results


def parse_lr_dump(lr_dump_path):
    """LR_Items_Dump.txt 를 파싱하여 {state_id: [after_dot_sequence, ...]} 반환.

    after_dot_sequence: precedence/alias 정규화 후의 문자열.
    """
    state_candidates = defaultdict(set)

    if not os.path.exists(lr_dump_path):
        print(f"[Error] LR dump not found: {lr_dump_path}")
        return state_candidates

    current_state = None

    with open(lr_dump_path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")

            # State header
            m = re.match(r'^State (\d+):$', line)
            if m:
                current_state = int(m.group(1))
                continue

            if current_state is None:
                continue

            # Skip empty or header lines
            stripped = line.strip()
            if not stripped or stripped.startswith("===") or stripped.startswith("("):
                continue

            # Find • position
            dot_idx = stripped.find('•')
            if dot_idx < 0:
                continue

            # Extract after-dot text (before [Lookahead:])
            after_dot = stripped[dot_idx + len('•'):]
            la_idx = after_dot.find('[Lookahead:')
            if la_idx >= 0:
                after_dot = after_dot[:la_idx]
            after_dot = after_dot.strip()

            if not after_dot:
                # dot at end of production (completed item) — no candidate
                continue

            normalized_set = normalize_after_dot(after_dot)
            state_candidates[current_state].update(normalized_set)

    return state_candidates


def _apply_sym_aliases(tokens):
    """외부 스캐너 토큰/내부 심볼 이름을 LR item 이름으로 변환한 변형들을 생성."""
    # runtime name → possible LR item names
    SYM_MAP = {
        '"':  ['_string_start', '_string_end', '_symbol_start'],
        "'":  ['_string_start', '_string_end'],
        ')':  ['_string_end', '_subshell_end', '_regex_end',
               '_string_array_end', '_symbol_array_end'],
        '[':  ['_element_reference_bracket'],
        '`':  ['_subshell_start'],
    }

    # 첫 번째 토큰에 대해 변형 생성
    if not tokens:
        return [tokens]

    variants = [tokens]
    first = tokens[0]
    if first in SYM_MAP:
        for alt in SYM_MAP[first]:
            variants.append([alt] + tokens[1:])

    # 마지막 토큰에 대해서도 변형 생성
    result = []
    for v in variants:
        result.append(v)
        last = v[-1]
        if last in SYM_MAP:
            for alt in SYM_MAP[last]:
                result.append(v[:-1] + [alt])

    return result


def candidate_matches_lr(candidate, lr_sequences):
    """candidate 문자열이 해당 state의 LR sequences 중 하나와 매치되는지 확인.

    매치 기준:
      1. 정확히 일치 (심볼 alias 변형 포함)
      2. candidate가 LR sequence의 prefix
      3. LR sequence가 candidate의 prefix
    """
    cand_tokens = candidate.split()
    if not cand_tokens:
        return False, None

    # 심볼 alias 변형 생성
    cand_variants = _apply_sym_aliases(cand_tokens)

    for seq in lr_sequences:
        seq_tokens = seq.split()
        if not seq_tokens:
            continue

        for cand_t in cand_variants:
            # 정확히 일치
            if cand_t == seq_tokens:
                return True, seq

            # candidate가 LR sequence의 prefix
            if len(cand_t) <= len(seq_tokens):
                if seq_tokens[:len(cand_t)] == cand_t:
                    return True, seq

            # LR sequence가 candidate의 prefix
            if len(seq_tokens) <= len(cand_t):
                if cand_t[:len(seq_tokens)] == seq_tokens:
                    return True, seq

    # fuzzy: 첫 번째 토큰만 매치 (변형 포함)
    first_tokens = set(v[0] for v in cand_variants if v)
    for seq in lr_sequences:
        seq_tokens = seq.split()
        if seq_tokens and seq_tokens[0] in first_tokens:
            return True, seq

    return False, None


# ===========================================================
# Breakdown 파싱
# ===========================================================

def parse_breakdown(breakdown_str):
    """Top10_Breakdown 문자열을 파싱."""
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


# ===========================================================
# 검증 로직
# ===========================================================

def verify_all(lang, lr_state_cands, rank_min=None, rank_max=None):
    """rank_miss_breakdown 의 모든 (state, candidate) 쌍을 검증."""
    breakdown_path = os.path.join(REPORT_BASE, lang, f"rank_miss_breakdown_{lang}.csv")
    if not os.path.exists(breakdown_path):
        print(f"  [{lang}] breakdown CSV not found")
        return [], {}

    # 집계용
    pair_results = Counter()  # (state, candidate) -> OK/NOT_FOUND count
    pair_status = {}          # (state, candidate) -> "OK" | "NOT_FOUND"
    cand_stats = defaultdict(lambda: {"ok": 0, "nf": 0, "total_score_ok": 0, "total_score_nf": 0})
    csv_rows = []

    with open(breakdown_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            final_rank = int(row["Final_Rank"])
            if rank_min and final_rank < rank_min:
                continue
            if rank_max and final_rank > rank_max:
                continue

            candidates = parse_breakdown(row.get("Top10_Breakdown", ""))
            for cand in candidates:
                for state_id, score in cand["states"]:
                    pair_key = (state_id, cand["name"])

                    # 캐시된 결과 사용
                    if pair_key in pair_status:
                        status = pair_status[pair_key]
                    else:
                        lr_seqs = lr_state_cands.get(state_id, set())
                        matched, matched_seq = candidate_matches_lr(cand["name"], lr_seqs)
                        status = "OK" if matched else "NOT_FOUND"
                        pair_status[pair_key] = status

                    if status == "OK":
                        cand_stats[cand["name"]]["ok"] += 1
                        cand_stats[cand["name"]]["total_score_ok"] += score
                    else:
                        cand_stats[cand["name"]]["nf"] += 1
                        cand_stats[cand["name"]]["total_score_nf"] += score

    # CSV 출력용: unique (state, candidate) 쌍
    for (state_id, cand_name), status in sorted(pair_status.items()):
        lr_seqs = lr_state_cands.get(state_id, set())
        matched, matched_seq = candidate_matches_lr(cand_name, lr_seqs)
        csv_rows.append({
            "State": state_id,
            "Candidate": cand_name,
            "Status": status,
            "Matching_LR_Item": matched_seq or "",
            "LR_Sequences_Count": len(lr_seqs),
        })

    return csv_rows, cand_stats


def save_results(lang, csv_rows, cand_stats):
    out_dir = os.path.join(REPORT_BASE, lang)
    os.makedirs(out_dir, exist_ok=True)

    # 1. 상세 CSV
    csv_path = os.path.join(out_dir, f"lr_verification_{lang}.csv")
    fieldnames = ["State", "Candidate", "Status", "Matching_LR_Item", "LR_Sequences_Count"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_rows)
    print(f"  [Saved] {csv_path} ({len(csv_rows)} pairs)")

    # 2. 요약
    total_ok = sum(1 for r in csv_rows if r["Status"] == "OK")
    total_nf = sum(1 for r in csv_rows if r["Status"] == "NOT_FOUND")
    total = total_ok + total_nf

    summary_path = os.path.join(out_dir, f"lr_verification_summary_{lang}.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"=== LR Verification Summary: {lang} ===\n\n")
        f.write(f"Total unique (state, candidate) pairs: {total}\n")
        f.write(f"  OK:        {total_ok} ({total_ok/total*100:.1f}%)\n" if total > 0 else "")
        f.write(f"  NOT_FOUND: {total_nf} ({total_nf/total*100:.1f}%)\n\n" if total > 0 else "")

        f.write(f"{'Candidate':<50} {'OK':>6} {'NF':>6} {'Score_OK':>14} {'Score_NF':>14}\n")
        f.write(f"{'-'*90}\n")
        for name, stats in sorted(cand_stats.items(), key=lambda x: x[1]["nf"], reverse=True):
            if stats["nf"] > 0 or stats["ok"] > 0:
                f.write(f"{name:<50} {stats['ok']:>6} {stats['nf']:>6} "
                        f"{stats['total_score_ok']:>14,} {stats['total_score_nf']:>14,}\n")

        # NOT_FOUND 상세
        nf_rows = [r for r in csv_rows if r["Status"] == "NOT_FOUND"]
        if nf_rows:
            f.write(f"\n\n=== NOT_FOUND Details ===\n\n")
            for r in sorted(nf_rows, key=lambda x: (x["Candidate"], x["State"])):
                f.write(f"  State {r['State']:>5}: {r['Candidate']}\n")

    print(f"  [Saved] {summary_path}")

    # 콘솔 출력
    print(f"\n  Total pairs: {total}")
    print(f"    OK:        {total_ok} ({total_ok/total*100:.1f}%)" if total > 0 else "")
    print(f"    NOT_FOUND: {total_nf} ({total_nf/total*100:.1f}%)" if total > 0 else "")

    if total_nf > 0:
        print(f"\n  NOT_FOUND candidates (by frequency):")
        nf_cands = {name: stats for name, stats in cand_stats.items() if stats["nf"] > 0}
        for name, stats in sorted(nf_cands.items(), key=lambda x: x[1]["nf"], reverse=True)[:20]:
            print(f"    {name:<50} NF={stats['nf']:>6}  score={stats['total_score_nf']:>14,}")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rank_min = rank_max = None
    for i, a in enumerate(sys.argv[1:]):
        if a == "--rank" and i + 3 <= len(sys.argv):
            rank_min = int(sys.argv[i + 2])
            rank_max = int(sys.argv[i + 3])

    if not args:
        print(f"Usage: python3 verify_lr_candidates.py <language> [--rank MIN MAX]")
        print(f"Available: {', '.join(LANG_CONFIGS.keys())}")
        sys.exit(1)

    lang = args[0].lower()
    if lang not in LANG_CONFIGS:
        print(f"Unknown language: {lang}")
        sys.exit(1)

    cfg = LANG_CONFIGS[lang]

    print(f"\n[*] Language: {lang}")
    print(f"[*] Parsing LR_Items_Dump...")
    lr_state_cands = parse_lr_dump(cfg["lr_dump"])
    print(f"    Loaded {len(lr_state_cands)} states")

    print(f"[*] Verifying (state, candidate) pairs...")
    csv_rows, cand_stats = verify_all(lang, lr_state_cands, rank_min, rank_max)

    save_results(lang, csv_rows, cand_stats)
    print(f"\n[*] Done.")


if __name__ == "__main__":
    main()
