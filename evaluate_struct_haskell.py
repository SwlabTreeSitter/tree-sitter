import sys
import os
import json
import subprocess
import time
import csv
import re
from collections import defaultdict

# =================[ 설정 및 경로 ]=================

EXE_PATH = "/home/hyeonjin/PL/tree-sitter/TreeSitterCutFile.exe"
LIB_PATH = "/home/hyeonjin/PL/tree-sitter-haskell/haskell.so"

SOURCE_DIR = "/home/hyeonjin/PL/codecompletion_benchmarks/haskell/TEST"
ANSWER_DIR = "/home/hyeonjin/PL/tree-sitter/reports/haskell"
REPORT_DIR = "/home/hyeonjin/PL/tree-sitter/reports/haskell"
DB_PATH    = "/home/hyeonjin/PL/code-completion-extension/resources/haskell/candidates.json"

MAX_CANDIDATE_LIST_SIZE = 20

SKIP_DIRS = {".git", "build", "dist", "dist-newstyle", ".stack-work"}

# =========================================================

class FileReporter:
    def __init__(self, project: str = None):
        self.project = project  # None = 전체
        self.db = self._load_json(DB_PATH)

        # 커버리지 통계
        self.total_queries   = 0
        self.found_count     = 0
        self.not_found_count = 0
        self.fail_count      = 0

        # 랭크 통계
        self.rank_stats         = defaultdict(int)
        self.beyond_top20_count = 0

        self.file_reports = []

        os.makedirs(REPORT_DIR, exist_ok=True)

    def _load_json(self, path):
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _run_at_position(self, target_file, row, col):
        cmd = [EXE_PATH, "haskell", LIB_PATH, target_file, str(row), str(col), "0"]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace"
            )
            if result.returncode != 0:
                return []
            for line in result.stdout.splitlines():
                match = re.search(r"@@PREDICT:\s*([\d\s]+)", line)
                if match:
                    raw = match.group(1).strip()
                    if not raw:
                        return []
                    states = []
                    for s in raw.split():
                        try:
                            states.append(int(s))
                        except ValueError:
                            pass
                    return states
            return []
        except Exception:
            return []

    def _lookup_db_full(self, states):
        """커버리지용: 크기 제한 없이 DB에서 모든 후보 조회."""
        merged = defaultdict(int)
        for state in states:
            s_key = str(state)
            if s_key in self.db:
                for item in self.db[s_key]:
                    merged[item["key"]] += item["value"]
        return merged

    def _lookup_db_ranked(self, states):
        """Top-N 랭크 계산용: 점수 내림차순 정렬된 (key, score) 리스트 반환."""
        merged = defaultdict(int)
        for state in states:
            s_key = str(state)
            if s_key in self.db:
                for item in self.db[s_key]:
                    merged[item["key"]] += item["value"]
        return sorted(merged.items(), key=lambda x: x[1], reverse=True)

    def _get_rank(self, candidates, ground_truth):
        gt_clean = ground_truth.replace(" ", "")
        for rank, (key, _) in enumerate(candidates, 1):
            if key.replace(" ", "") == gt_clean:
                return rank
        return 0

    def _is_found(self, candidates_map: dict, ground_truth: str) -> bool:
        gt_clean = ground_truth.replace(" ", "")
        for key in candidates_map:
            if key.replace(" ", "") == gt_clean:
                return True
        return False

    def _safe_name(self, target_file):
        try:
            rel = os.path.relpath(target_file, SOURCE_DIR)
        except ValueError:
            rel = os.path.basename(target_file)
        return rel.replace(os.path.sep, "_").replace("..", "")

    def _save_debug_log(self, safe_name, log_data):
        debug_dir = os.path.join(REPORT_DIR, "debug_coverage_haskell")
        os.makedirs(debug_dir, exist_ok=True)
        csv_path = os.path.join(debug_dir, f"{safe_name}.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Location", "Ground_Truth", "State_List", "Coverage_Result", "Rank"])
            writer.writerows(log_data)

    def evaluate_file(self, target_file):
        safe_name = self._safe_name(target_file)
        json_path = os.path.join(ANSWER_DIR, safe_name + ".json")

        if not os.path.exists(json_path):
            return

        answers = self._load_json(json_path)
        if not answers:
            return

        f_total     = 0
        f_found     = 0
        f_not_found = 0
        f_fail      = 0
        f_top1      = 0
        f_top3      = 0
        f_top5      = 0
        f_top10     = 0
        f_top20     = 0
        debug_logs  = []

        total_locs = len(answers)
        processed  = 0
        print(f" -> {safe_name} ({total_locs} points)...")

        for loc_key, gt_data in answers.items():
            processed += 1
            if processed % 10 == 0:
                print(f"    {processed}/{total_locs}...", end="\r")

            nums = re.findall(r"\d+", loc_key)
            if len(nums) < 2:
                continue
            row, col = int(nums[0]), int(nums[1])

            ground_truth = gt_data.get("candidate", "")
            if not ground_truth:
                continue

            states = self._run_at_position(target_file, row, col)

            if not states:
                result_label = "FAIL"
                rank = 0
                f_fail += 1
            else:
                # 커버리지: 제한 없이 전체 DB 조회
                candidates_full = self._lookup_db_full(states)
                if self._is_found(candidates_full, ground_truth):
                    result_label = "FOUND"
                    f_found += 1
                else:
                    result_label = "NOT_FOUND"
                    f_not_found += 1

                # 랭크: Top-20 제한 조회
                top_candidates = self._lookup_db_ranked(states)[:MAX_CANDIDATE_LIST_SIZE]
                rank = self._get_rank(top_candidates, ground_truth)
                if rank > 0:
                    self.rank_stats[rank] += 1
                    if rank == 1:  f_top1  += 1
                    if rank <= 3:  f_top3  += 1
                    if rank <= 5:  f_top5  += 1
                    if rank <= 10: f_top10 += 1
                    if rank <= 20: f_top20 += 1
                elif result_label == "NOT_FOUND":
                    self.beyond_top20_count += 1

            debug_logs.append([loc_key, ground_truth, str(states) if states else "FAIL", result_label, rank])
            f_total += 1
            self.total_queries += 1

        print(f"    Done. ({f_total} queries)")

        self.found_count     += f_found
        self.not_found_count += f_not_found
        self.fail_count      += f_fail

        self.file_reports.append({
            "name":      safe_name,
            "total":     f_total,
            "found":     f_found,
            "not_found": f_not_found,
            "fail":      f_fail,
            "top1":      f_top1,
            "top3":      f_top3,
            "top5":      f_top5,
            "top10":     f_top10,
            "top20":     f_top20,
        })
        self._save_debug_log(safe_name, debug_logs)

    def _report_suffix(self):
        return f"_{self.project}" if self.project else ""

    def save_report(self):
        suffix = self._report_suffix()

        # 파일별 성능 리포트 (랭크 + 커버리지 통합)
        perf_path = os.path.join(REPORT_DIR, f"haskell_file_performance{suffix}.csv")
        with open(perf_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "File Name", "Total",
                "Top-1 Acc (%)", "Top-3 Acc (%)", "Top-5 Acc (%)", "Top-10 Acc (%)", "Top-20 Acc (%)",
                "Found", "Found (%)", "Not Found", "Not Found (%)", "Fail", "Fail (%)"
            ])
            for r in self.file_reports:
                total = r["total"]
                def pct(n): return round(n / total * 100, 2) if total > 0 else 0.0
                writer.writerow([
                    r["name"], total,
                    pct(r["top1"]), pct(r["top3"]), pct(r["top5"]), pct(r["top10"]), pct(r["top20"]),
                    r["found"],     pct(r["found"]),
                    r["not_found"], pct(r["not_found"]),
                    r["fail"],      pct(r["fail"]),
                ])
        print(f"[Saved] File Report (CSV) -> {perf_path}")

        # 커버리지 전용 리포트
        cov_path = os.path.join(REPORT_DIR, f"haskell_coverage{suffix}.csv")
        with open(cov_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "File Name", "Total",
                "Found", "Found (%)",
                "Not Found", "Not Found (%)",
                "Fail", "Fail (%)"
            ])
            for r in self.file_reports:
                total = r["total"]
                def pct(n): return round(n / total * 100, 2) if total > 0 else 0.0
                writer.writerow([
                    r["name"], total,
                    r["found"],     pct(r["found"]),
                    r["not_found"], pct(r["not_found"]),
                    r["fail"],      pct(r["fail"]),
                ])
        print(f"[Saved] Coverage Report (CSV) -> {cov_path}")

    def _collect_files(self):
        search_root = os.path.join(SOURCE_DIR, self.project) if self.project else SOURCE_DIR
        if not os.path.isdir(search_root):
            print(f"[Error] Project directory not found: {search_root}")
            print(f"Available projects: {', '.join(sorted(os.listdir(SOURCE_DIR)))}")
            sys.exit(1)

        target_files = []
        for root, dirs, files in os.walk(search_root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for filename in files:
                if filename.endswith(".hs"):
                    target_files.append(os.path.join(root, filename))
        return sorted(target_files)

    def run(self):
        label = self.project if self.project else "ALL"
        files = self._collect_files()

        print(f"[*] Language  : haskell")
        print(f"[*] Project   : {label}")
        print(f"[*] Found {len(files)} .hs files. Starting evaluation...")

        start = time.time()
        for idx, f in enumerate(files):
            print(f" [{idx+1}/{len(files)}]", end=" ")
            self.evaluate_file(f)

        elapsed = time.time() - start
        print(f"\n[*] Analysis Complete in {elapsed:.2f} sec.\n")

        q = self.total_queries
        if q > 0:
            global_top10 = sum(self.rank_stats[r] for r in range(1, 11))
            global_top20 = sum(self.rank_stats[r] for r in range(1, 21))

            print(f"[{label}] Total Queries : {q}")
            print(f"[{label}] Top-10 Count  : {global_top10}  ({global_top10/q*100:.1f}%)")
            print(f"[{label}] Top11~20      : {global_top20 - global_top10}")
            print(f"[{label}] Beyond Top-20 : {self.beyond_top20_count}")
            print(f"[{label}] CPP Fail      : {self.fail_count}")
            print()
            print(f"[{label}] Found         : {self.found_count}  ({self.found_count/q*100:.1f}%)")
            print(f"[{label}] Not Found     : {self.not_found_count}  ({self.not_found_count/q*100:.1f}%)")
            print(f"[{label}] Fail          : {self.fail_count}  ({self.fail_count/q*100:.1f}%)")

        self.save_report()


if __name__ == "__main__":
    # 사용법:
    #   python evaluate_struct_haskell.py                        # 전체 평가
    #   python evaluate_struct_haskell.py LPFP                   # 특정 프로젝트만
    #   python evaluate_struct_haskell.py Programming-in-Haskell
    #   python evaluate_struct_haskell.py learn-haskell-by-example-main

    project = sys.argv[1] if len(sys.argv) > 1 else None
    reporter = FileReporter(project=project)
    reporter.run()
