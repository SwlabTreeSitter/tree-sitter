import os
import glob
import json
import subprocess
import time
import csv
import re
from collections import defaultdict

# =================[ 설정 및 경로 ]=================

# 1. 실행 파일 및 라이브러리 경로 (PHP 언어용)
EXE_PATH = "/home/hyeonjin/PL/tree-sitter/TreeSitterCutFile.exe"
LIB_PATH = "/home/hyeonjin/PL/tree-sitter-php/php/parser.so"

# 2. 데이터셋 및 정답지 경로
SOURCE_DIR = "/home/hyeonjin/PL/codecompletion_benchmarks/php/TEST"
ANSWER_DIR = "/home/hyeonjin/PL/tree-sitter/reports/php"
REPORT_DIR = "/home/hyeonjin/PL/tree-sitter/reports/php"

# 3. DB 경로 (구조 후보 추천용)
DB_PATH = "/home/hyeonjin/PL/code-completion-extension/resources/php/candidates.json"

# 4. Exercism 프로젝트 (수집 시와 동일한 필터 적용)
EXERCISM_PROJECT = "php-main"

# 5. 평가 설정
MAX_CANDIDATE_LIST_SIZE = 20
MAX_RANK_CHECK = 20

# =========================================================

def is_exercism_target(rel_path_unix: str) -> bool:
    """collect 스크립트와 동일한 필터: .meta/example.php, .meta/exemplar.php 만 대상"""
    parts = rel_path_unix.split("/")
    if len(parts) >= 2:
        parent_dir = parts[-2]
        filename   = parts[-1]
        if parent_dir == ".meta" and filename in ("example.php", "exemplar.php"):
            return True
    return False

class FileReporter:
    def __init__(self):
        self.db = self.load_json(DB_PATH)

        self.rank_stats = defaultdict(int)
        self.beyond_top20_count = 0
        self.cpp_fail_count = 0
        self.global_queries = 0
        self.global_files = 0
        self.file_reports = []

        if not os.path.exists(REPORT_DIR):
            os.makedirs(REPORT_DIR)
        else:
            for csv_file in ["php_file_performance.csv", "php_rank_distribution.csv"]:
                path = os.path.join(REPORT_DIR, csv_file)
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass

    def load_json(self, path):
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def run_cpp_at_position(self, target_file, row, col):
        cmd = [EXE_PATH, "php", LIB_PATH, target_file, str(row), str(col), "0"]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace'
            )

            if result.returncode != 0:
                return []

            for line in result.stdout.splitlines():
                match = re.search(r"@@PREDICT:\s*([\d\s]+)", line)
                if match:
                    raw_nums = match.group(1).strip()
                    if not raw_nums:
                        return []

                    states = []
                    for num_str in raw_nums.split():
                        try:
                            states.append(int(num_str))
                        except ValueError:
                            pass

                    return states

            return []

        except Exception:
            return []

    def lookupDB(self, states):
        merged_map = defaultdict(int)
        for state in states:
            s_key = str(state)
            if s_key in self.db:
                for item in self.db[s_key]:
                    merged_map[item['key']] += item['value']

        return sorted(merged_map.items(), key=lambda x: x[1], reverse=True)

    def get_rank(self, candidates, ground_truth):
        gt_clean = ground_truth.replace(" ", "")
        for rank, (key, val) in enumerate(candidates, 1):
            key_clean = key.replace(" ", "")
            if key_clean == gt_clean:
                return rank
        return 0

    def save_debug_log(self, safe_name, log_data):
        debug_dir = os.path.join(REPORT_DIR, "debug_states_php")
        if not os.path.exists(debug_dir):
            os.makedirs(debug_dir)

        csv_path = os.path.join(debug_dir, f"{safe_name}.csv")

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Location", "Ground_Truth", "State_List", "Rank"])
            writer.writerows(log_data)

    def evaluate_file(self, target_file):
        try:
            rel_path = os.path.relpath(target_file, SOURCE_DIR)
        except ValueError:
            rel_path = os.path.basename(target_file)

        safe_name = rel_path.replace(os.path.sep, "_").replace("..", "")
        json_name = safe_name + ".json"
        json_path = os.path.join(ANSWER_DIR, json_name)

        if not os.path.exists(json_path):
            return

        answers = self.load_json(json_path)
        if not answers:
            return

        file_query_count = 0
        file_top1_count = 0
        file_top3_count = 0
        file_top5_count = 0
        file_top10_count = 0
        file_top20_count = 0
        debug_logs = []

        total_locations = len(answers)
        processed_locs = 0
        print(f" -> Analyzing {safe_name} ({total_locations} points)...")

        for loc_key, gt_data in answers.items():
            processed_locs += 1
            if processed_locs % 10 == 0:
                print(f"    Processing {processed_locs}/{total_locations}...", end="\r")

            nums = re.findall(r'\d+', loc_key)
            if len(nums) >= 2:
                row, col = int(nums[0]), int(nums[1])
            else:
                continue

            ground_truth = gt_data.get("candidate", "")
            if not ground_truth: continue

            predicted_states = self.run_cpp_at_position(target_file, row, col)

            state_str = str(predicted_states) if predicted_states else "FAIL"

            rank = 0
            if predicted_states:
                full_candidates = self.lookupDB(predicted_states)
                top_candidates = full_candidates[:MAX_CANDIDATE_LIST_SIZE]
                rank = self.get_rank(top_candidates, ground_truth)

            debug_logs.append([loc_key, ground_truth, state_str, rank])

            self.global_queries += 1
            file_query_count += 1

            if rank > 0:
                self.rank_stats[rank] += 1
                if rank == 1: file_top1_count += 1
                if 1 <= rank <= 3: file_top3_count += 1
                if 1 <= rank <= 5: file_top5_count += 1
                if 1 <= rank <= 10: file_top10_count += 1
                if 1 <= rank <= 20: file_top20_count += 1
            elif not predicted_states:
                self.cpp_fail_count += 1
            else:
                self.beyond_top20_count += 1

        print(f"    Done. ({file_query_count} queries)")

        self.global_files += 1
        self.file_reports.append({
            "name": safe_name,
            "total": file_query_count,
            "top1": file_top1_count,
            "top3": file_top3_count,
            "top5": file_top5_count,
            "top10": file_top10_count,
            "top20": file_top20_count
        })

        self.save_debug_log(safe_name, debug_logs)

    def save_file_performance_report(self):
        csv_path = os.path.join(REPORT_DIR, "php_file_performance.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Safe File Name", "Total Queries", "Top-1 Acc (%)", "Top-3 Acc (%)", "Top-5 Acc (%)", "Top-10 Acc (%)", "Top-20 Acc (%)"])

            for report in self.file_reports:
                total = report["total"]
                acc1  = (report["top1"]  / total * 100) if total > 0 else 0.0
                acc3  = (report["top3"]  / total * 100) if total > 0 else 0.0
                acc5  = (report["top5"]  / total * 100) if total > 0 else 0.0
                acc10 = (report["top10"] / total * 100) if total > 0 else 0.0
                acc20 = (report["top20"] / total * 100) if total > 0 else 0.0

                writer.writerow([report['name'], total, round(acc1, 2), round(acc3, 2), round(acc5, 2), round(acc10, 2), round(acc20, 2)])

        print(f"[Saved] File Report (CSV) -> {csv_path}")

    def run(self):
        target_files = []
        for root, dirs, files in os.walk(SOURCE_DIR):
            dirs[:] = [d for d in dirs if d not in {".git", "vendor", "node_modules"}]
            for file in files:
                if not file.endswith(".php"):
                    continue

                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, SOURCE_DIR)
                rel_path_unix = rel_path.replace(os.path.sep, "/")
                top_project = rel_path_unix.split("/")[0]

                # collect 스크립트와 동일한 필터 적용
                if top_project == EXERCISM_PROJECT:
                    if not is_exercism_target(rel_path_unix):
                        continue

                target_files.append(full_path)

        print(f"[*] Found {len(target_files)} target '.php' files. Starting Iterative Analysis...")

        start = time.time()
        for idx, f in enumerate(target_files):
            print(f" [{idx+1}/{len(target_files)}] Processing...", end="\r")
            self.evaluate_file(f)

        elapsed = time.time() - start
        print(f"\n[*] Analysis Complete in {elapsed:.2f} sec.\n")

        global_top10 = sum(self.rank_stats[r] for r in range(1, 11))
        global_top20 = sum(self.rank_stats[r] for r in range(1, 21))
        global_11_to_20 = global_top20 - global_top10
        if self.global_queries > 0:
            print(f"[Global] Total Queries    : {self.global_queries}")
            print(f"[Global] Top-10 Count     : {global_top10}")
            print(f"[Global] Top-10 Acc       : {global_top10 / self.global_queries * 100:.1f}%")
            print(f"[Global] Top11~20 Count   : {global_11_to_20}")
            print(f"[Global] Beyond Top-20    : {self.beyond_top20_count}")
            print(f"[Global] CPP Fail         : {self.cpp_fail_count}")

        self.save_file_performance_report()

if __name__ == "__main__":
    reporter = FileReporter()
    reporter.run()
