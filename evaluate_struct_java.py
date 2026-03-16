import os
import json
import subprocess
import time
import csv
import re
from collections import defaultdict

# =================[ 설정 및 경로 ]=================

EXE_PATH = "/home/hyeonjin/PL/tree-sitter/TreeSitterCutFile.exe"
LIB_PATH = "/home/hyeonjin/PL/tree-sitter-java/java.so"

SOURCE_DIR = "/home/hyeonjin/PL/codecompletion_benchmarks/java/TEST"
ANSWER_DIR = "/home/hyeonjin/PL/tree-sitter/reports/java"
REPORT_DIR = "/home/hyeonjin/PL/tree-sitter/reports/java"

DB_PATH = "/home/hyeonjin/PL/code-completion-extension/resources/java/candidates.json"

EXERCISM_PROJECT = "java-main"

TARGET_EXTENSIONS = {".java"}
MAX_CANDIDATE_LIST_SIZE = 20

# =========================================================

def is_exercism_target(rel_path_unix: str) -> bool:
    return "/.meta/src/reference/java/" in rel_path_unix

class FileReporter:
    def __init__(self):
        self.db = self.load_json(DB_PATH)

        self.rank_stats = defaultdict(int)
        self.beyond_top20_count = 0
        self.java_fail_count = 0
        self.global_queries = 0
        self.global_files = 0
        self.file_reports = []

        if not os.path.exists(REPORT_DIR):
            os.makedirs(REPORT_DIR)
        else:
            for csv_file in ["java_file_performance.csv", "java_rank_distribution.csv"]:
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

    def run_java_at_position(self, target_file, row, col):
        cmd = [EXE_PATH, "java", LIB_PATH, target_file, str(row), str(col), "0"]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding='utf-8', errors='replace'
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
            if key.replace(" ", "") == gt_clean:
                return rank
        return 0

    def save_debug_log(self, safe_name, log_data):
        debug_dir = os.path.join(REPORT_DIR, "debug_states_java")
        if not os.path.exists(debug_dir):
            os.makedirs(debug_dir)
        with open(os.path.join(debug_dir, f"{safe_name}.csv"), "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Location", "Ground_Truth", "State_List", "Rank"])
            writer.writerows(log_data)

    def evaluate_file(self, target_file):
        try:
            rel_path = os.path.relpath(target_file, SOURCE_DIR)
        except ValueError:
            rel_path = os.path.basename(target_file)

        safe_name = rel_path.replace(os.path.sep, "_").replace("..", "")
        json_path = os.path.join(ANSWER_DIR, safe_name + ".json")

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
            if len(nums) < 2:
                continue
            row, col = int(nums[0]), int(nums[1])

            ground_truth = gt_data.get("candidate", "")
            if not ground_truth:
                continue

            predicted_states = self.run_java_at_position(target_file, row, col)
            state_str = str(predicted_states) if predicted_states else "FAIL"

            rank = 0
            if predicted_states:
                top_candidates = self.lookupDB(predicted_states)[:MAX_CANDIDATE_LIST_SIZE]
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
                self.java_fail_count += 1
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
        csv_path = os.path.join(REPORT_DIR, "java_file_performance.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Safe File Name", "Total Queries", "Top-1 Acc (%)", "Top-3 Acc (%)", "Top-5 Acc (%)", "Top-10 Acc (%)", "Top-20 Acc (%)"])
            for report in self.file_reports:
                total = report["total"]
                acc = lambda k: round(report[k] / total * 100, 2) if total > 0 else 0.0
                writer.writerow([report['name'], total, acc('top1'), acc('top3'), acc('top5'), acc('top10'), acc('top20')])
        print(f"[Saved] File Report (CSV) -> {csv_path}")

    def run(self):
        target_files = []
        for root, dirs, files in os.walk(SOURCE_DIR):
            dirs[:] = [d for d in dirs if d not in {".git", "build", "target"}]
            for filename in files:
                _, ext = os.path.splitext(filename)
                if ext.lower() not in TARGET_EXTENSIONS:
                    continue

                full_path = os.path.join(root, filename)
                rel_path = os.path.relpath(full_path, SOURCE_DIR)
                rel_path_unix = rel_path.replace(os.path.sep, "/")
                top_project = rel_path_unix.split("/")[0]

                if top_project == EXERCISM_PROJECT:
                    if not is_exercism_target(rel_path_unix):
                        continue

                target_files.append(full_path)

        print(f"[*] Found {len(target_files)} target Java files. Starting Iterative Analysis...")

        start = time.time()
        for idx, f in enumerate(target_files):
            print(f" [{idx+1}/{len(target_files)}] Processing...", end="\r")
            self.evaluate_file(f)

        elapsed = time.time() - start
        print(f"\n[*] Analysis Complete in {elapsed:.2f} sec.\n")

        global_top10 = sum(self.rank_stats[r] for r in range(1, 11))
        global_top20 = sum(self.rank_stats[r] for r in range(1, 21))
        if self.global_queries > 0:
            print(f"[Global] Total Queries    : {self.global_queries}")
            print(f"[Global] Top-10 Count     : {global_top10}")
            print(f"[Global] Top-10 Acc       : {global_top10 / self.global_queries * 100:.1f}%")
            print(f"[Global] Top11~20 Count   : {global_top20 - global_top10}")
            print(f"[Global] Beyond Top-20    : {self.beyond_top20_count}")
            print(f"[Global] Java Fail        : {self.java_fail_count}")

        self.save_file_performance_report()

if __name__ == "__main__":
    reporter = FileReporter()
    reporter.run()
