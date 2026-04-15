#!/usr/bin/env python3
"""
plot_rank_distribution.py

debug_coverage_<lang>/*.csv 에서 Rank 빈도를 집계하여
언어별 랭크 분포 그래프를 생성한다.

출력:
  reports/<lang>/<lang>_rank_distribution.png   (언어별 개별)
  reports/all_rank_distribution.png             (전체 언어 비교)

사용법:
  python3 plot_rank_distribution.py                    # 전체 언어
  python3 plot_rank_distribution.py haskell java       # 특정 언어만
"""

import sys
import os
import csv
from collections import Counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPORT_BASE = "/home/hyeonjin/PL/tree-sitter/reports"

ALL_LANGUAGES = ["smallbasic", "c", "haskell", "ruby", "php", "javascript", "cpp", "java", "python"]


def collect_ranks(lang):
    """debug CSV 에서 Rank > 0 인 빈도를 Counter 로 반환."""
    debug_dir = os.path.join(REPORT_BASE, lang, f"debug_coverage_{lang}")
    if not os.path.isdir(debug_dir):
        return Counter()

    ranks = Counter()
    for fname in os.listdir(debug_dir):
        if not fname.endswith(".csv"):
            continue
        with open(os.path.join(debug_dir, fname), encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                r = int(row.get("Rank", "0"))
                if r > 0:
                    ranks[r] += 1
    return ranks


def plot_single(lang, ranks):
    """언어 1개의 랭크 분포 그래프."""
    if not ranks:
        print(f"  [{lang}] No rank data.")
        return

    x = sorted(ranks.keys())
    y = [ranks[k] for k in x]
    total = sum(y)
    max_rank = max(x)

    # 누적 비율 계산
    cumulative = []
    running = 0
    for k in x:
        running += ranks[k]
        cumulative.append(running / total * 100)

    fig, ax1 = plt.subplots(figsize=(14, 6))

    # 바 차트: 빈도
    ax1.bar(x, y, color="steelblue", alpha=0.7, label="Frequency")
    ax1.set_xlabel("Rank", fontsize=12)
    ax1.set_ylabel("Frequency", fontsize=12, color="steelblue")
    ax1.tick_params(axis="y", labelcolor="steelblue")

    # 누적 비율 라인
    ax2 = ax1.twinx()
    ax2.plot(x, cumulative, color="red", linewidth=1.5, label="Cumulative %")
    ax2.set_ylabel("Cumulative %", fontsize=12, color="red")
    ax2.tick_params(axis="y", labelcolor="red")
    ax2.set_ylim(0, 105)

    # Top-N 기준선
    for n, color, ls in [(10, "green", "--"), (20, "orange", "--"), (50, "purple", ":")]:
        if n <= max_rank:
            ax1.axvline(x=n, color=color, linestyle=ls, alpha=0.6, label=f"Top-{n}")

    ax1.set_title(f"{lang} — Rank Distribution (total={total:,}, max_rank={max_rank})", fontsize=14)
    ax1.legend(loc="upper left", fontsize=9)
    ax2.legend(loc="upper right", fontsize=9)

    plt.tight_layout()
    out_path = os.path.join(REPORT_BASE, lang, f"{lang}_rank_distribution.png")
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"  [{lang}] Saved: {out_path}  (max_rank={max_rank}, total={total:,})")


def plot_combined(all_ranks):
    """전체 언어 비교: 누적 분포 곡선."""
    fig, ax = plt.subplots(figsize=(14, 7))

    colors = plt.cm.tab10.colors

    for i, (lang, ranks) in enumerate(all_ranks.items()):
        if not ranks:
            continue

        max_rank = max(ranks.keys())
        total = sum(ranks.values())
        x = list(range(1, max_rank + 1))
        running = 0
        cumulative = []
        for r in x:
            running += ranks.get(r, 0)
            cumulative.append(running / total * 100)

        ax.plot(x, cumulative, color=colors[i % len(colors)], linewidth=1.8, label=f"{lang} (n={total:,}, max={max_rank})")
        # max rank 위치에 마커 표시
        ax.plot(max_rank, cumulative[-1], marker='|', markersize=10, color=colors[i % len(colors)])

    ax.set_xlabel("Rank", fontsize=12)
    ax.set_ylabel("Cumulative %", fontsize=12)
    ax.set_title("Rank Cumulative Distribution — All Languages", fontsize=14)
    ax.set_ylim(0, 105)
    max_rank = max(max(ranks.keys()) for ranks in all_ranks.values() if ranks)
    ax.set_xlim(0, max_rank + 10)
    ax.axhline(y=90, color="gray", linestyle=":", alpha=0.5)
    ax.axhline(y=95, color="gray", linestyle=":", alpha=0.5)
    ax.axhline(y=99, color="gray", linestyle=":", alpha=0.5)
    ax.axvline(x=10, color="gray", linestyle="--", alpha=0.3)
    ax.axvline(x=20, color="gray", linestyle="--", alpha=0.3)
    ax.axvline(x=50, color="gray", linestyle="--", alpha=0.3)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.2)

    plt.tight_layout()
    out_path = os.path.join(REPORT_BASE, "all_rank_distribution.png")
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"\n  [ALL] Saved: {out_path}")


def collect_all_results(lang):
    """debug CSV 에서 전체 행을 4구간으로 분류."""
    debug_dir = os.path.join(REPORT_BASE, lang, f"debug_coverage_{lang}")
    if not os.path.isdir(debug_dir):
        return {}

    bins = {"Top-1~10": 0, "Top-11~20": 0, "Rest": 0, "NOT_FOUND": 0}

    for fname in os.listdir(debug_dir):
        if not fname.endswith(".csv"):
            continue
        with open(os.path.join(debug_dir, fname), encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                r = int(row.get("Rank", "0"))
                result = row.get("Coverage_Result", "")
                if 1 <= r <= 10:
                    bins["Top-1~10"] += 1
                elif 11 <= r <= 20:
                    bins["Top-11~20"] += 1
                elif r > 20:
                    bins["Rest"] += 1
                else:
                    bins["NOT_FOUND"] += 1
    return bins


def plot_stacked_overview(all_results):
    """전체 언어의 100% 스택 가로 바 차트."""
    categories = ["Top-1~10", "Top-11~20", "Rest", "NOT_FOUND"]
    colors = ["#2ecc71", "#f9e79f", "#e74c3c", "#8e44ad"]

    langs = [l for l in all_results if all_results[l]]
    if not langs:
        return

    fig, ax = plt.subplots(figsize=(12, max(4, len(langs) * 0.7)))

    for i, cat in enumerate(categories):
        lefts = []
        values = []
        for lang in langs:
            total = sum(all_results[lang].values())
            pct = all_results[lang].get(cat, 0) / total * 100 if total > 0 else 0
            values.append(pct)
            left = 0
            for prev_cat in categories[:i]:
                left += all_results[lang].get(prev_cat, 0) / total * 100 if total > 0 else 0
            lefts.append(left)

        bars = ax.barh(langs, values, left=lefts, color=colors[i], label=cat,
                       edgecolor="white", linewidth=0.5)

        # 비율 라벨 표시 (2% 이상만)
        for j, (v, l) in enumerate(zip(values, lefts)):
            if v >= 2:
                ax.text(l + v / 2, j, f"{v:.1f}%", ha="center", va="center", fontsize=8)

    # 총 쿼리 수 표시
    for j, lang in enumerate(langs):
        total = sum(all_results[lang].values())
        pass  # 쿼리수 표시 제거

    ax.set_xlabel("Percentage (%)", fontsize=11)
    ax.set_xlim(0, 100)
    ax.set_title("Query Result Distribution — All Languages", fontsize=13)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=4, fontsize=10)
    ax.invert_yaxis()

    plt.tight_layout()
    out_path = os.path.join(REPORT_BASE, "all_rank_overview.png")
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\n  [ALL] Overview saved: {out_path}")


def print_summary(all_ranks):
    """언어별 주요 수치 출력."""
    print(f"\n{'Language':<12} {'Total':>8} {'Max':>5} {'Top-10':>8} {'Top-20':>8} {'Top-50':>8} {'Top-100':>8}")
    print("-" * 62)
    for lang, ranks in all_ranks.items():
        if not ranks:
            continue
        total = sum(ranks.values())
        max_r = max(ranks.keys())
        top10 = sum(ranks.get(r, 0) for r in range(1, 11))
        top20 = sum(ranks.get(r, 0) for r in range(1, 21))
        top50 = sum(ranks.get(r, 0) for r in range(1, 51))
        top100 = sum(ranks.get(r, 0) for r in range(1, 101))
        print(f"{lang:<12} {total:>8,} {max_r:>5} {top10/total*100:>7.1f}% {top20/total*100:>7.1f}% {top50/total*100:>7.1f}% {top100/total*100:>7.1f}%")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    languages = args if args else ALL_LANGUAGES

    all_ranks = {}
    all_results = {}
    for lang in languages:
        print(f"  [{lang}] Collecting...")
        ranks = collect_ranks(lang)
        all_ranks[lang] = ranks
        all_results[lang] = collect_all_results(lang)
        plot_single(lang, ranks)

    if len(all_ranks) > 1:
        plot_combined(all_ranks)
        plot_stacked_overview(all_results)

    print_summary(all_ranks)


if __name__ == "__main__":
    main()
