"""
generate_project_performance.py

debug_coverage_<lang>/*.csv 를 읽어 프로젝트 폴더 단위로 집계한 뒤
모든 언어 결과를 하나의 CSV 로 출력한다.

출력: reports/all_project_performance.csv
"""

import os
import csv
from collections import defaultdict

LANG_CONFIGS = {
    "c": {
        "src":    "/home/hyeonjin/PL/codecompletion_benchmarks/c11/TEST_BENCH/ansi_c",
        "report": "/home/hyeonjin/PL/tree-sitter/reports/c11",
        "debug_dir_name": "debug_coverage_c",
    },
    "haskell": {
        "src":    "/home/hyeonjin/PL/codecompletion_benchmarks/haskell/TEST",
        "report": "/home/hyeonjin/PL/tree-sitter/reports/haskell",
        "debug_dir_name": "debug_coverage_haskell",
    },
    "ruby": {
        "src":    "/home/hyeonjin/PL/codecompletion_benchmarks/ruby/TEST",
        "report": "/home/hyeonjin/PL/tree-sitter/reports/ruby",
        "debug_dir_name": "debug_coverage_ruby",
    },
    "php": {
        "src":    "/home/hyeonjin/PL/codecompletion_benchmarks/php/TEST",
        "report": "/home/hyeonjin/PL/tree-sitter/reports/php",
        "debug_dir_name": "debug_coverage_php",
    },
    "javascript": {
        "src":    "/home/hyeonjin/PL/codecompletion_benchmarks/javascript/TEST",
        "report": "/home/hyeonjin/PL/tree-sitter/reports/javascript",
        "debug_dir_name": "debug_coverage_javascript",
    },
    "cpp": {
        "src":    "/home/hyeonjin/PL/codecompletion_benchmarks/cpp/TEST",
        "report": "/home/hyeonjin/PL/tree-sitter/reports/cpp",
        "debug_dir_name": "debug_coverage_cpp",
    },
    "java": {
        "src":    "/home/hyeonjin/PL/codecompletion_benchmarks/java/TEST",
        "report": "/home/hyeonjin/PL/tree-sitter/reports/java",
        "debug_dir_name": "debug_coverage_java",
    },
    "python": {
        "src":    "/home/hyeonjin/PL/codecompletion_benchmarks/python/TEST",
        "report": "/home/hyeonjin/PL/tree-sitter/reports/python",
        "debug_dir_name": "debug_coverage_python",
    },
}

OUTPUT_PATH = "/home/hyeonjin/PL/tree-sitter/reports/all_project_performance.csv"


def get_projects(src_dir):
    """src 디렉터리 아래 1단계 서브디렉터리 목록 반환."""
    if not os.path.isdir(src_dir):
        return []
    return sorted(
        e for e in os.listdir(src_dir)
        if os.path.isdir(os.path.join(src_dir, e))
    )


def aggregate_project(debug_dir, project):
    """프로젝트 prefix 로 시작하는 debug CSV 를 집계해 dict 반환."""
    prefix = project + "_"
    counts = defaultdict(int)

    for fname in sorted(os.listdir(debug_dir)):
        if not (fname.startswith(prefix) and fname.endswith(".csv")):
            continue
        with open(os.path.join(debug_dir, fname), encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                result = row.get("Coverage_Result", "")
                try:
                    rank = int(row.get("Rank", "0"))
                except ValueError:
                    rank = 0

                counts["total"] += 1
                if result == "FOUND":
                    counts["found"] += 1
                elif result == "NOT_FOUND":
                    counts["not_found"] += 1
                elif result == "FAIL":
                    counts["fail"] += 1

                if 0 < rank <= 1:  counts["top1"]  += 1
                if 0 < rank <= 3:  counts["top3"]  += 1
                if 0 < rank <= 5:  counts["top5"]  += 1
                if 0 < rank <= 10: counts["top10"] += 1
                if 0 < rank <= 20: counts["top20"] += 1

    return counts


def pct(n, total):
    return round(n / total * 100, 2) if total > 0 else 0.0


def main():
    rows = []

    for lang, cfg in LANG_CONFIGS.items():
        debug_dir = os.path.join(cfg["report"], cfg["debug_dir_name"])
        if not os.path.isdir(debug_dir):
            print(f"[{lang}] debug_dir not found: {debug_dir}")
            continue

        projects = get_projects(cfg["src"])
        if not projects:
            print(f"[{lang}] no projects found in {cfg['src']}")
            continue

        for project in projects:
            c = aggregate_project(debug_dir, project)
            if c["total"] == 0:
                continue
            t = c["total"]
            rows.append({
                "Language":       lang,
                "Project":        project,
                "Total":          t,
                "Top-1 Acc (%)":  pct(c["top1"],  t),
                "Top-3 Acc (%)":  pct(c["top3"],  t),
                "Top-5 Acc (%)":  pct(c["top5"],  t),
                "Top-10 Acc (%)": pct(c["top10"], t),
                "Top-20 Acc (%)": pct(c["top20"], t),
                "Found":          c["found"],
                "Found (%)":      pct(c["found"],     t),
                "Not Found":      c["not_found"],
                "Not Found (%)":  pct(c["not_found"], t),
                "Fail":           c["fail"],
                "Fail (%)":       pct(c["fail"],      t),
            })
            print(f"  [{lang}] {project}: total={t}")

    fieldnames = [
        "Language", "Project", "Total",
        "Top-1 Acc (%)", "Top-3 Acc (%)", "Top-5 Acc (%)",
        "Top-10 Acc (%)", "Top-20 Acc (%)",
        "Found", "Found (%)", "Not Found", "Not Found (%)", "Fail", "Fail (%)",
    ]
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n[Saved] {OUTPUT_PATH}  ({len(rows)} projects)")


if __name__ == "__main__":
    main()
