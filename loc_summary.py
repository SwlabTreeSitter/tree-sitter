import csv
from collections import defaultdict

# ==========================================================
# 논문 수치 (Ranked Syntax Completion with LR Parsing)
# ==========================================================
# C:     LEARN = cJSON-1.7.15 + lcc-4.2 + cdsa(c336c7e) + bc-1.07
#               + gzip-1.12 + screen-4.9.0 + make-4.4 + tar-1.34
#        TEST  = Kernighan & Ritchie C 교재 연습문제 솔루션
# SB:    LEARN = SmallBasic 커뮤니티 프로그램
#        TEST  = Microsoft SmallBasic tutorial 프로그램
PAPER = {
    ("c",          "LEARN"): {"files": None, "lines": 308_599},
    ("c",          "TEST"):  {"files": 106,  "lines": 11_218},
    ("smallbasic", "LEARN"): {"files": 3_701, "lines": 789_023},
    ("smallbasic", "TEST"):  {"files": 27,   "lines": 155},
}

# ==========================================================
# 현재 측정치 로드
# ==========================================================
d = defaultdict(lambda: [0, 0, 0])
with open('loc_report.csv') as f:
    r = csv.DictReader(f)
    for row in r:
        key = (row['Language'], row['Set'])
        d[key][0] += int(row['Files'])
        d[key][1] += int(row['Total_Lines_wc'])
        d[key][2] += int(row['Code_Lines_cloc'])


# ==========================================================
# [1] 현재 측정치 (전 언어, LEARN/TEST)
# ==========================================================
for set_name in ['LEARN', 'TEST']:
    print(f"\n=== 현재 측정 ({set_name}) ===")
    print(f"{'Lang':<12} {'Files':>8} {'Total(wc)':>12} {'Code(cloc)':>12}")
    for (lang, s), (files, total, code) in sorted(d.items()):
        if s != set_name:
            continue
        print(f"{lang:<12} {files:>8} {total:>12} {code:>12}")


# ==========================================================
# [2] 논문 수치 (C, SmallBasic만)
# ==========================================================
print(f"\n=== 논문 수치 (C, SmallBasic) ===")
print(f"{'Lang':<12} {'Set':<6} {'Files':>8} {'Total(wc)':>12}")
for (lang, s), v in sorted(PAPER.items()):
    files_str = f"{v['files']}" if v['files'] is not None else "N/A"
    print(f"{lang:<12} {s:<6} {files_str:>8} {v['lines']:>12}")


# ==========================================================
# [3] 비교 (C, SmallBasic): 현재 vs 논문
# ==========================================================
print(f"\n=== 비교 (현재 vs 논문) ===")
print(f"{'Lang':<12} {'Set':<6} "
      f"{'Files(now)':>10} {'Files(paper)':>12} "
      f"{'Lines(now)':>12} {'Lines(paper)':>12} "
      f"{'Match?':>8}")
for (lang, s), p in sorted(PAPER.items()):
    cur = d.get((lang, s), [0, 0, 0])
    cur_files, cur_lines = cur[0], cur[1]
    p_files = p['files']
    p_lines = p['lines']

    files_ok = (p_files is None) or (cur_files == p_files)
    lines_ok = cur_lines == p_lines
    match = "✓" if (files_ok and lines_ok) else "✗"

    p_files_str = f"{p_files}" if p_files is not None else "N/A"
    print(f"{lang:<12} {s:<6} "
          f"{cur_files:>10} {p_files_str:>12} "
          f"{cur_lines:>12} {p_lines:>12} "
          f"{match:>8}")
