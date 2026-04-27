"""
aggregate_per_project.py

언어별 debug_coverage_<lang>/*.csv 를 프로젝트(=TEST 1단계 서브디렉터리) 단위로 집계해
프로젝트별 file_performance / coverage CSV 를 생성하고 stdout 에 요약 블록을 출력한다.

evaluate_coverage.py 가 만든 debug CSV 를 그대로 입력으로 사용하므로 평가를 다시 수행하지 않는다.
프로젝트 그룹핑 규칙(TEST 1단계 서브디렉터리, prefix 매칭)은 generate_project_performance.py 와 동일하다.

사용법:
    python aggregate_per_project.py <language>

출력:
    reports/<lang>/<lang>_file_performance_<project>.csv
    reports/<lang>/<lang>_coverage_<project>.csv
"""

import sys
import os
import csv
from collections import defaultdict

from generate_project_performance import LANG_CONFIGS, get_projects


def aggregate_per_file(debug_dir, project):
    """프로젝트 prefix 로 시작하는 debug CSV 들을 파일별로 카운트한다.

    Returns:
        (file_reports, totals)
        file_reports — 파일당 dict 리스트 (CSV 출력용)
        totals       — 프로젝트 합계 dict (stdout 요약용, beyond 포함)
    """
    prefix = project + "_"
    file_reports = []
    totals = defaultdict(int)

    csv_files = sorted(
        f for f in os.listdir(debug_dir)
        if f.startswith(prefix) and f.endswith(".csv")
    )

    for fname in csv_files:
        c = defaultdict(int)
        with open(os.path.join(debug_dir, fname), encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                result = row.get("Coverage_Result", "")
                try:
                    rank = int(row.get("Rank", "0"))
                except ValueError:
                    rank = 0

                c["total"] += 1
                if result == "FOUND":
                    c["found"] += 1
                elif result == "NOT_FOUND":
                    c["not_found"] += 1
                    if rank == 0:
                        totals["beyond"] += 1
                elif result == "FAIL":
                    c["fail"] += 1

                if 0 < rank <= 1:  c["top1"]  += 1
                if 0 < rank <= 3:  c["top3"]  += 1
                if 0 < rank <= 5:  c["top5"]  += 1
                if 0 < rank <= 10: c["top10"] += 1
                if 0 < rank <= 20: c["top20"] += 1

        file_reports.append({
            "name":      fname[:-4],
            "total":     c["total"],
            "found":     c["found"],
            "not_found": c["not_found"],
            "fail":      c["fail"],
            "top1":      c["top1"],
            "top3":      c["top3"],
            "top5":      c["top5"],
            "top10":     c["top10"],
            "top20":     c["top20"],
        })
        for k, v in c.items():
            totals[k] += v

    return file_reports, totals


def write_file_performance_csv(report_dir, lang, project, file_reports):
    path = os.path.join(report_dir, f"{lang}_file_performance_{project}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "File Name", "Total",
            "Top-1 Acc (%)", "Top-3 Acc (%)", "Top-5 Acc (%)",
            "Top-10 Acc (%)", "Top-20 Acc (%)",
            "Found", "Found (%)", "Not Found", "Not Found (%)", "Fail", "Fail (%)"
        ])
        for r in file_reports:
            t = r["total"]
            def pct(n): return round(n / t * 100, 2) if t > 0 else 0.0
            writer.writerow([
                r["name"], t,
                pct(r["top1"]), pct(r["top3"]), pct(r["top5"]),
                pct(r["top10"]), pct(r["top20"]),
                r["found"],     pct(r["found"]),
                r["not_found"], pct(r["not_found"]),
                r["fail"],      pct(r["fail"]),
            ])
    print(f"[Saved] {path}")


def write_coverage_csv(report_dir, lang, project, file_reports):
    path = os.path.join(report_dir, f"{lang}_coverage_{project}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "File Name", "Total",
            "Found", "Found (%)",
            "Not Found", "Not Found (%)",
            "Fail", "Fail (%)"
        ])
        for r in file_reports:
            t = r["total"]
            def pct(n): return round(n / t * 100, 2) if t > 0 else 0.0
            writer.writerow([
                r["name"], t,
                r["found"],     pct(r["found"]),
                r["not_found"], pct(r["not_found"]),
                r["fail"],      pct(r["fail"]),
            ])
    print(f"[Saved] {path}")


def print_project_summary(project, totals):
    total = totals["total"]
    print(f"[{project}] Total Queries : {total}")
    print(f"[{project}] Top-10 Count  : {totals['top10']}")
    print(f"[{project}] Top11~20      : {totals['top20'] - totals['top10']}")
    print(f"[{project}] Beyond Top-20 : {totals['beyond']}")
    print(f"[{project}] CPP Fail      : {totals['fail']}")
    print()
    print(f"[{project}] Found         : {totals['found']}  ({totals['found']/total*100:.1f}%)")
    print(f"[{project}] Not Found     : {totals['not_found']}  ({totals['not_found']/total*100:.1f}%)")
    print(f"[{project}] Fail          : {totals['fail']}  ({totals['fail']/total*100:.1f}%)")


def run_for_language(lang):
    if lang not in LANG_CONFIGS:
        print(f"[Error] Unknown language: '{lang}'")
        print(f"Available: {', '.join(LANG_CONFIGS.keys())}")
        return

    cfg = LANG_CONFIGS[lang]
    debug_dir = os.path.join(cfg["report"], cfg["debug_dir_name"])

    if not os.path.isdir(debug_dir):
        print(f"[{lang}] debug_dir not found: {debug_dir}")
        return

    projects = get_projects(cfg["src"])
    if not projects:
        print(f"[{lang}] No project subdirectories under {cfg['src']} (skip).")
        return

    print(f"[*] Language: {lang}")
    print(f"[*] Projects: {len(projects)}\n")

    for project in projects:
        file_reports, totals = aggregate_per_file(debug_dir, project)
        if totals["total"] == 0:
            continue
        print_project_summary(project, totals)
        write_file_performance_csv(cfg["report"], lang, project, file_reports)
        write_coverage_csv(cfg["report"], lang, project, file_reports)
        print()


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("Usage: python aggregate_per_project.py <language>")
        print(f"Available: {', '.join(LANG_CONFIGS.keys())}")
        sys.exit(1)

    run_for_language(args[0].lower())
