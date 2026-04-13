#!/usr/bin/env python3
"""
analyze_not_found.py
NOT_FOUND 케이스를 분석합니다.

정답 JSON의 state_id가 State_List에 포함되는지 여부로 두 가지 케이스를 구분합니다:
  state_correct  : State_List에 정답 state_id 포함 → 상태는 맞게 예측됐으나 DB에 패턴 없음
  state_wrong    : State_List에 정답 state_id 없음 → 컨버전이 잘못된 상태를 예측
  no_state_info  : 정답 JSON에서 해당 위치의 state_id를 확인 불가

사용법:
  python3 analyze_not_found.py                  # 전체 언어
  python3 analyze_not_found.py haskell python   # 지정 언어만
"""

import os
import csv
import json
import ast
import sys
from collections import defaultdict

REPORTS_ROOT = "/home/hyeonjin/PL/tree-sitter/reports"

# (리포트 디렉터리명, debug_coverage_<key> 키, strip_ext 여부)
LANG_CONFIGS = {
    "smallbasic": ("smallbasic", "smallbasic", True),
    "c":        ("c",        "c",           False),
    "haskell":    ("haskell",    "haskell",     False),
    "ruby":       ("ruby",       "ruby",        False),
    "php":        ("php",        "php",         False),
    "javascript": ("javascript", "javascript",  False),
    "cpp":        ("cpp",        "cpp",         False),
    "java":       ("java",       "java",        False),
    "python":     ("python",     "python",      False),
}


def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_state_list(raw):
    """State_List 컬럼 문자열을 파이썬 리스트로 변환. 실패 시 None 반환."""
    if not raw or raw.strip() == "FAIL":
        return None
    try:
        val = ast.literal_eval(raw.strip())
        if isinstance(val, list):
            return val
    except Exception:
        pass
    return None


def analyze_lang(lang, report_dir, debug_key, strip_ext):
    debug_dir = os.path.join(REPORTS_ROOT, report_dir, f"debug_coverage_{debug_key}")
    answer_dir = os.path.join(REPORTS_ROOT, report_dir)

    if not os.path.isdir(debug_dir):
        print(f"  [Skip] debug directory not found: {debug_dir}")
        return None

    csv_files = sorted(f for f in os.listdir(debug_dir) if f.endswith(".csv"))
    if not csv_files:
        print(f"  [Skip] No CSV files found in {debug_dir}")
        return None

    total_nf       = 0
    state_correct  = 0   # state_id in State_List → DB에 패턴 없음
    state_wrong    = 0   # state_id not in State_List → 컨버전 오류
    no_state_info  = 0   # 정답 JSON에서 state_id 확인 불가

    # 상세 샘플 (state_wrong 케이스 최대 10개)
    wrong_samples  = []

    for csv_fname in csv_files:
        safe_name = csv_fname[:-4]  # .csv 제거

        # 대응하는 정답 JSON 경로
        if strip_ext:
            base, _ = os.path.splitext(safe_name)
            json_path = os.path.join(answer_dir, base + ".json")
        else:
            json_path = os.path.join(answer_dir, safe_name + ".json")

        answers = load_json(json_path)

        csv_path = os.path.join(debug_dir, csv_fname)
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("Coverage_Result") != "NOT_FOUND":
                    continue

                total_nf += 1
                location   = row.get("Location", "")
                gt         = row.get("Ground_Truth", "")
                state_list = parse_state_list(row.get("State_List", ""))

                # 정답 JSON에서 state_id 목록 조회 (list 형식)
                ans_entries = answers.get(location, [])
                state_ids   = [e["state_id"] for e in ans_entries] if ans_entries else []

                if not state_ids or state_list is None:
                    no_state_info += 1
                elif any(sid in state_list for sid in state_ids):
                    state_correct += 1
                else:
                    state_wrong += 1
                    if len(wrong_samples) < 10:
                        wrong_samples.append({
                            "file":       safe_name,
                            "location":   location,
                            "ground_truth": gt,
                            "state_ids":  state_ids[:5],
                            "state_list": state_list[:5],  # 처음 5개만
                        })

    return {
        "lang":          lang,
        "total_nf":      total_nf,
        "state_correct": state_correct,
        "state_wrong":   state_wrong,
        "no_state_info": no_state_info,
        "wrong_samples": wrong_samples,
    }


def print_results(results):
    print()
    print("=" * 70)
    print(f"  NOT_FOUND 분석 결과")
    print("=" * 70)
    print(f"{'언어':<14} {'총NOT_FOUND':>12} {'상태OK(DB없음)':>15} {'상태오류':>10} {'정보없음':>10}")
    print("-" * 70)

    for r in results:
        if r is None:
            continue
        lang = r["lang"]
        nf   = r["total_nf"]
        sc   = r["state_correct"]
        sw   = r["state_wrong"]
        ni   = r["no_state_info"]
        sc_pct = f"{sc/nf*100:.1f}%" if nf > 0 else "-"
        sw_pct = f"{sw/nf*100:.1f}%" if nf > 0 else "-"
        print(f"{lang:<14} {nf:>12,}  {sc:>8,} ({sc_pct:>6})  {sw:>6,} ({sw_pct:>6})  {ni:>8,}")

    print("=" * 70)
    print()
    print("  [상태OK(DB없음)] : State_List에 정답 state_id 포함 → DB 보강으로 해결 가능")
    print("  [상태오류]       : State_List에 정답 state_id 없음 → 컨버전 로직 문제")
    print("  [정보없음]       : 정답 JSON 누락 또는 state_id 필드 없음")
    print()

    for r in results:
        if r is None or not r["wrong_samples"]:
            continue
        print(f"  [{r['lang']}] state_wrong 샘플 (최대 10개):")
        for s in r["wrong_samples"]:
            print(f"    파일    : {s['file']}")
            print(f"    위치    : {s['location']}")
            print(f"    GT      : {s['ground_truth']}")
            print(f"    정답IDs : {s['state_ids']}")
            print(f"    예측    : {s['state_list']} ...")
            print()


def save_csv(results):
    out_path = os.path.join(REPORTS_ROOT, "not_found_analysis.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Language", "Total_NOT_FOUND",
            "State_Correct", "State_Correct_%",
            "State_Wrong",   "State_Wrong_%",
            "No_State_Info",
        ])
        for r in results:
            if r is None:
                continue
            nf = r["total_nf"]
            pct = lambda n: round(n / nf * 100, 2) if nf > 0 else 0.0
            writer.writerow([
                r["lang"], nf,
                r["state_correct"], pct(r["state_correct"]),
                r["state_wrong"],   pct(r["state_wrong"]),
                r["no_state_info"],
            ])
    print(f"[Saved] {out_path}")


if __name__ == "__main__":
    req_langs = [a.lower() for a in sys.argv[1:] if not a.startswith("--")]
    langs = req_langs if req_langs else list(LANG_CONFIGS.keys())

    results = []
    for lang in langs:
        if lang not in LANG_CONFIGS:
            print(f"[Error] Unknown language: {lang}")
            continue
        report_dir, debug_key, strip_ext = LANG_CONFIGS[lang]
        print(f"[*] Analyzing {lang} ...")
        r = analyze_lang(lang, report_dir, debug_key, strip_ext)
        results.append(r)

    print_results(results)
    save_csv(results)
