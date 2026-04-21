#!/usr/bin/env python3
"""
rq1_three_metrics.py

선행연구의 세 가지 근거를 9개 언어 전체에 일관된 방식으로 추출한다.

근거 1  Coverage         = FOUND cursors / total cursors
근거 2a 다운키 0회 비율   = (Rank==1) / FOUND  (1순위 정답 비율)
근거 2b 평균 다운키       = mean(Rank - 1) over FOUND
근거 3  Top-K            = (1 <= Rank <= K) / FOUND  (K=5, 10)

소스: reports/<lang>/debug_coverage_<lang>/*.csv  (per-cursor, 컬럼 Rank / Coverage_Result)

출력:
  reports/rq1_three_metrics.csv
  reports/rq1_three_metrics.md
"""

import csv
import os
import statistics
import sys

REPORT_BASE = "/home/hyeonjin/PL/tree-sitter/reports"

LANG_ORDER = [
    ("smallbasic", "LR"),
    ("c",          "LR"),
    ("php",        "GLR"),
    ("haskell",    "GLR"),
    ("java",       "GLR"),
    ("javascript", "GLR"),
    ("python",     "GLR"),
    ("cpp",        "GLR"),
    ("ruby",       "GLR"),
]


def collect_lang(lang):
    dbg_dir = os.path.join(REPORT_BASE, lang, f"debug_coverage_{lang}")
    if not os.path.isdir(dbg_dir):
        return None

    total = 0
    found = 0
    ranks = []

    for fname in os.listdir(dbg_dir):
        if not fname.endswith(".csv"):
            continue
        with open(os.path.join(dbg_dir, fname), encoding="utf-8") as f:
            for row in csv.DictReader(f):
                total += 1
                try:
                    rk = int(row.get("Rank", "0"))
                except ValueError:
                    rk = 0
                if row.get("Coverage_Result") == "FOUND" and rk >= 1:
                    found += 1
                    ranks.append(rk)

    if not ranks:
        return None

    rank_1 = sum(1 for r in ranks if r == 1)
    top5 = sum(1 for r in ranks if r <= 5)
    top10 = sum(1 for r in ranks if r <= 10)
    downkeys = [r - 1 for r in ranks]

    return {
        "total":       total,
        "found":       found,
        "coverage":    100.0 * found / total,
        "rank1":       rank_1,
        "rank1_pct":   100.0 * rank_1 / found,
        "top5_pct":    100.0 * top5 / found,
        "top10_pct":   100.0 * top10 / found,
        "avg_downkey": statistics.mean(downkeys),
        "med_downkey": statistics.median(downkeys),
    }


def format_md(rows):
    hdr = (
        "| Language    | Cat | Cursors | Coverage | Rank-1    | Avg↓keys | Med↓keys | Top-5  | Top-10 |\n"
        "|-------------|-----|---------|----------|-----------|----------|----------|--------|--------|\n"
    )
    lines = []
    for lang, cat, m in rows:
        if m is None:
            lines.append(f"| {lang:<11} | {cat:<3} | - | - | - | - | - | - | - |")
            continue
        lines.append(
            f"| {lang:<11} | {cat:<3} | {m['total']:>7} | "
            f"{m['coverage']:>6.2f}% | "
            f"{m['rank1']:>5} ({m['rank1_pct']:>4.1f}%) | "
            f"{m['avg_downkey']:>7.2f} | "
            f"{m['med_downkey']:>7.1f} | "
            f"{m['top5_pct']:>5.2f}% | "
            f"{m['top10_pct']:>5.2f}% |"
        )
    return hdr + "\n".join(lines) + "\n"


def main():
    rows = []
    for lang, cat in LANG_ORDER:
        m = collect_lang(lang)
        rows.append((lang, cat, m))

    csv_path = os.path.join(REPORT_BASE, "rq1_three_metrics.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "Language", "Category", "Cursors", "Found",
            "Coverage_pct", "Rank1_count", "Rank1_pct",
            "Avg_Downkey", "Median_Downkey",
            "Top5_pct", "Top10_pct",
        ])
        for lang, cat, m in rows:
            if m is None:
                w.writerow([lang, cat, "", "", "", "", "", "", "", "", ""])
                continue
            w.writerow([
                lang, cat,
                m["total"], m["found"],
                f"{m['coverage']:.2f}", m["rank1"], f"{m['rank1_pct']:.2f}",
                f"{m['avg_downkey']:.2f}", f"{m['med_downkey']:.1f}",
                f"{m['top5_pct']:.2f}", f"{m['top10_pct']:.2f}",
            ])

    md_path = os.path.join(REPORT_BASE, "rq1_three_metrics.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# RQ1 — Three Metrics (Coverage / Ranking / Top-10)\n\n")
        f.write("Evidence categories follow prior work (SmallBasic/C):\n")
        f.write("- **Coverage**: fraction of cursors where a candidate set is retrievable.\n")
        f.write("- **Rank-1 / Avg↓keys**: ranking usefulness (0 keystrokes when rank=1).\n")
        f.write("- **Top-5 / Top-10**: answer found within visible page.\n\n")
        f.write(format_md(rows))
        f.write("\nMetric definitions: computed over FOUND cursors in `debug_coverage_<lang>/*.csv`.\n")
        f.write("`Cat` = LR (prior work) or GLR (this work extension via tree-sitter).\n")

    print(f"[Saved] {csv_path}")
    print(f"[Saved] {md_path}")
    print()
    print(format_md(rows))


if __name__ == "__main__":
    main()
