import os
import glob
import json
import subprocess
import time
import csv
import re
from collections import defaultdict

# =================[ 설정 및 경로 ]=================

# 실행 파일 및 라이브러리 경로
EXE_PATH = "/home/hyeonjin/PL/tree-sitter/TreeSitterCutFile.exe"
LIB_PATH = "/home/hyeonjin/PL/tree-sitter-smallbasic/smallbasic.so"

# 데이터셋 경로 (소스 파일 .sb)
SOURCE_DIR = "/home/hyeonjin/PL/codecompletion_benchmarks/smallbasic/TEST_BENCH"

# 정답지 경로 (.json 파일들이 있는 폴더)
ANSWER_DIR = "/home/hyeonjin/PL/tree-sitter/reports/smallbasic"

# 리포트 저장 경로
REPORT_DIR = "/home/hyeonjin/PL/tree-sitter/reports/smallbasic"

# DB 경로 (후보 추천용)
DB_PATH = "/home/hyeonjin/PL/code-completion-extension/resources/smallbasic/candidates.json"

# 평가 설정
MAX_CANDIDATE_LIST_SIZE = 20

# =========================================================

def is_tutorial_file(filename):
    """숫자로 시작하는 tutorial 파일만 선별"""
    basename = os.path.basename(filename)
    return basename[0].isdigit()

class FileReporter:
    def __init__(self):
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

    def _run_at_position(self, target_file, byte_offset):
        cmd = [EXE_PATH, "smallbasic", LIB_PATH, target_file, "--byte", str(byte_offset), "2"]
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
        except Exception as e:
            print(f"[Error] Failed to parse output at {row},{col} - {e}")
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

    def _save_debug_log(self, filename, log_data):
        debug_dir = os.path.join(REPORT_DIR, "debug_coverage_tutorial")
        os.makedirs(debug_dir, exist_ok=True)
        csv_path = os.path.join(debug_dir, f"{filename}.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Location", "Ground_Truth", "State_List", "Coverage_Result", "Rank"])
            writer.writerows(log_data)

    def evaluate_file(self, sb_file):
        filename = os.path.basename(sb_file)
        json_name = filename.replace(".sb", ".json")
        json_path = os.path.join(ANSWER_DIR, json_name)

        if not os.path.exists(json_path):
            print(f" [Skip] No Ground Truth for {filename}")
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
        print(f" -> {filename} ({total_locs} points)...")

        for loc_key, gt_data in answers.items():
            processed += 1
            if processed % 10 == 0:
                print(f"    {processed}/{total_locs}...", end="\r")

            try:
                byte_offset = int(loc_key)
            except ValueError:
                continue

            if not gt_data:
                continue

            states = self._run_at_position(sb_file, byte_offset)

            if not states:
                result_label = "FAIL"
                rank = 0
                f_fail += 1
                ground_truth = gt_data[0]["candidate"]
            else:
                # 커버리지: 제한 없이 전체 DB 조회
                candidates_full = self._lookup_db_full(states)
                if any(self._is_found(candidates_full, e["candidate"]) for e in gt_data):
                    result_label = "FOUND"
                    f_found += 1
                else:
                    result_label = "NOT_FOUND"
                    f_not_found += 1

                # 랭크: gt_data 후보들 중 가장 좋은(낮은) 순위
                top_candidates = self._lookup_db_ranked(states)[:MAX_CANDIDATE_LIST_SIZE]
                best_rank = 0
                best_entry = gt_data[0]
                for e in gt_data:
                    r = self._get_rank(top_candidates, e["candidate"])
                    if r > 0 and (best_rank == 0 or r < best_rank):
                        best_rank = r
                        best_entry = e
                rank = best_rank
                ground_truth = best_entry["candidate"]

                if rank > 0:
                    self.rank_stats[rank] += 1
                    if rank == 1:  f_top1  += 1
                    if rank <= 3:  f_top3  += 1
                    if rank <= 5:  f_top5  += 1
                    if rank <= 10: f_top10 += 1
                    if rank <= 20: f_top20 += 1

            debug_logs.append([loc_key, ground_truth, str(states) if states else "FAIL", result_label, rank])
            f_total += 1
            self.total_queries += 1

        print(f"    Done. ({f_total} queries)")

        self.found_count     += f_found
        self.not_found_count += f_not_found
        self.fail_count      += f_fail

        self.file_reports.append({
            "name":      filename,
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
        self._save_debug_log(filename, debug_logs)

    def save_report(self):
        # 파일별 성능 리포트 (랭크 + 커버리지 통합)
        perf_path = os.path.join(REPORT_DIR, "sb_file_performance_tutorial.csv")
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
        cov_path = os.path.join(REPORT_DIR, "sb_coverage_tutorial.csv")
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

    def run(self):
        all_files = glob.glob(os.path.join(SOURCE_DIR, "*.sb"))
        tutorial_files = sorted(f for f in all_files if is_tutorial_file(f))

        print(f"[*] Found {len(all_files)} total .sb files.")
        print(f"[*] Tutorial files (digit-starting): {len(tutorial_files)}")
        for f in tutorial_files:
            print(f"    {os.path.basename(f)}")
        print()

        start = time.time()
        for idx, f in enumerate(tutorial_files):
            print(f" [{idx+1}/{len(tutorial_files)}]", end=" ")
            self.evaluate_file(f)

        elapsed = time.time() - start
        print(f"\n[*] Analysis Complete in {elapsed:.2f} sec.\n")

        q = self.total_queries
        if q > 0:
            global_top10 = sum(self.rank_stats[r] for r in range(1, 11))
            global_top20 = sum(self.rank_stats[r] for r in range(1, 21))

            print(f"[Global] Total Queries    : {q}")
            print(f"[Global] Top-10 Count     : {global_top10}")
            print(f"[Global] Top-10 Acc       : {global_top10 / q * 100:.1f}%")
            print(f"[Global] Top11~20 Count   : {global_top20 - global_top10}")
            print(f"[Global] Beyond Top-20    : {self.beyond_top20_count}")
            print(f"[Global] CPP Fail         : {self.fail_count}")

            print(f"[SMALLBASIC-TUTORIAL] Total Queries : {q}")
            print(f"[SMALLBASIC-TUTORIAL] Found         : {self.found_count}  ({self.found_count/q*100:.1f}%)")
            print(f"[SMALLBASIC-TUTORIAL] Not Found     : {self.not_found_count}  ({self.not_found_count/q*100:.1f}%)")
            print(f"[SMALLBASIC-TUTORIAL] Fail          : {self.fail_count}  ({self.fail_count/q*100:.1f}%)")

        self.save_report()


if __name__ == "__main__":
    reporter = FileReporter()
    reporter.run()
