#!/usr/bin/env python3
"""
rq1_figures.py

Produce RQ1 figures from rq1_three_metrics.csv and rq1_structural_analysis.csv.

Outputs:
  reports/figures/rq1_fig1_three_metrics.png
  reports/figures/rq1_fig2_avg_downkeys.png
  reports/figures/rq1_fig3_concentration_scatter.png
"""

import csv
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPORT_BASE = "/home/hyeonjin/PL/tree-sitter/reports"
FIG_DIR = os.path.join(REPORT_BASE, "figures")
os.makedirs(FIG_DIR, exist_ok=True)

METRICS_CSV = os.path.join(REPORT_BASE, "rq1_three_metrics.csv")
STRUCT_CSV = os.path.join(REPORT_BASE, "rq1_structural_analysis.csv")

LR_COLOR = "#4e79a7"
GLR_COLOR = "#f28e2b"


def load_metrics():
    rows = []
    with open(METRICS_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if not r.get("Coverage_pct"):
                continue
            rows.append({
                "lang":     r["Language"],
                "cat":      r["Category"],
                "cov":      float(r["Coverage_pct"]),
                "rank1":    float(r["Rank1_pct"]),
                "avg_down": float(r["Avg_Downkey"]),
                "top5":     float(r["Top5_pct"]),
                "top10":    float(r["Top10_pct"]),
            })
    return rows


def load_structural():
    d = {}
    with open(STRUCT_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if not r.get("Top3_State_Concentration_pct"):
                continue
            d[r["Language"]] = float(r["Top3_State_Concentration_pct"])
    return d


def fig1_three_metrics(rows):
    langs = [r["lang"] for r in rows]
    cov = [r["cov"] for r in rows]
    top10 = [r["top10"] for r in rows]
    rank1 = [r["rank1"] for r in rows]
    colors = [LR_COLOR if r["cat"] == "LR" else GLR_COLOR for r in rows]

    x = np.arange(len(langs))
    w = 0.27

    fig, ax = plt.subplots(figsize=(11, 5.5))
    b1 = ax.bar(x - w, cov, w, label="Coverage", color=colors, alpha=0.95, edgecolor="black", linewidth=0.4)
    b2 = ax.bar(x, top10, w, label="Top-10", color=colors, alpha=0.65, edgecolor="black", linewidth=0.4, hatch="//")
    b3 = ax.bar(x + w, rank1, w, label="Rank-1", color=colors, alpha=0.35, edgecolor="black", linewidth=0.4, hatch="xx")

    ax.set_xticks(x)
    ax.set_xticklabels(langs, rotation=15)
    ax.set_ylabel("Percentage (%)")
    ax.set_ylim(0, 105)
    ax.set_title("RQ1: Three Metrics per Language (prior-work framework)")
    ax.axhline(90, color="gray", linestyle="--", linewidth=0.8, alpha=0.6)
    ax.text(len(langs) - 0.5, 90.5, "90%", fontsize=8, color="gray")

    # legend: grouped
    from matplotlib.patches import Patch
    legend_elems = [
        Patch(facecolor="white", edgecolor="black", label="Coverage"),
        Patch(facecolor="white", edgecolor="black", hatch="//", label="Top-10"),
        Patch(facecolor="white", edgecolor="black", hatch="xx", label="Rank-1"),
        Patch(facecolor=LR_COLOR, label="LR (prior)"),
        Patch(facecolor=GLR_COLOR, label="GLR (this work)"),
    ]
    ax.legend(handles=legend_elems, loc="lower right", fontsize=8, ncol=2)
    ax.grid(axis="y", linestyle=":", alpha=0.4)

    # number annotations on Top-10
    for i, v in enumerate(top10):
        ax.text(x[i], v + 0.6, f"{v:.1f}", ha="center", fontsize=7)

    plt.tight_layout()
    path = os.path.join(FIG_DIR, "rq1_fig1_three_metrics.png")
    plt.savefig(path, dpi=300)
    plt.close()
    print(f"[Saved] {path}")


def fig2_avg_downkeys(rows):
    rows_sorted = sorted(rows, key=lambda r: r["avg_down"])
    langs = [r["lang"] for r in rows_sorted]
    vals = [r["avg_down"] for r in rows_sorted]
    colors = [LR_COLOR if r["cat"] == "LR" else GLR_COLOR for r in rows_sorted]

    fig, ax = plt.subplots(figsize=(10, 4.5))
    bars = ax.bar(langs, vals, color=colors, edgecolor="black", linewidth=0.4)
    ax.set_ylabel("Average Down-Keys (Rank − 1)")
    ax.set_title("RQ1: Ranking Usefulness — Average Down-Keys per Language")
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    for i, v in enumerate(vals):
        ax.text(i, v + 0.03, f"{v:.2f}", ha="center", fontsize=8)

    # prior-work reference (C: 2.15)
    ax.axhline(2.15, color="gray", linestyle="--", linewidth=0.8, alpha=0.6)
    ax.text(len(langs) - 0.4, 2.18, "prior C: 2.15", fontsize=7, color="gray")

    from matplotlib.patches import Patch
    ax.legend(handles=[
        Patch(facecolor=LR_COLOR, label="LR (prior)"),
        Patch(facecolor=GLR_COLOR, label="GLR (this work)"),
    ], loc="upper left", fontsize=8)

    plt.tight_layout()
    path = os.path.join(FIG_DIR, "rq1_fig2_avg_downkeys.png")
    plt.savefig(path, dpi=300)
    plt.close()
    print(f"[Saved] {path}")


def fig3_concentration(rows, conc):
    xs, ys, labels, colors = [], [], [], []
    for r in rows:
        if r["lang"] not in conc:
            continue
        xs.append(conc[r["lang"]])
        ys.append(r["top10"])
        labels.append(r["lang"])
        colors.append(LR_COLOR if r["cat"] == "LR" else GLR_COLOR)

    fig, ax = plt.subplots(figsize=(8, 5.5))
    ax.scatter(xs, ys, c=colors, s=90, edgecolor="black", linewidth=0.5, zorder=3)
    for xi, yi, lbl in zip(xs, ys, labels):
        ax.annotate(lbl, (xi, yi), textcoords="offset points", xytext=(6, 4), fontsize=9)

    ax.set_xlabel("Top-3 State Noise Concentration (%)")
    ax.set_ylabel("Top-10 Accuracy (%)")
    ax.set_title("RQ1: Structural Noise Concentration vs. Top-10 Accuracy")
    ax.grid(linestyle=":", alpha=0.4)

    from matplotlib.patches import Patch
    ax.legend(handles=[
        Patch(facecolor=LR_COLOR, label="LR (prior)"),
        Patch(facecolor=GLR_COLOR, label="GLR (this work)"),
    ], loc="lower left", fontsize=8)

    plt.tight_layout()
    path = os.path.join(FIG_DIR, "rq1_fig3_concentration_scatter.png")
    plt.savefig(path, dpi=300)
    plt.close()
    print(f"[Saved] {path}")


def main():
    rows = load_metrics()
    conc = load_structural()

    fig1_three_metrics(rows)
    fig2_avg_downkeys(rows)
    fig3_concentration(rows, conc)


if __name__ == "__main__":
    main()
