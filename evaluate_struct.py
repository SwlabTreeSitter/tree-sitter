import sys
import os
import glob
import json
import subprocess
import time
from collections import defaultdict

# ==============================================================================
# [설정] 환경에 맞게 경로를 수정하세요.
# ==============================================================================
EXE_PATH = ".\\TreeSitterCutFile.exe"
DLL_PATH = ".\\smallbasic.dll"
DB_PATH = "..\\moniExtension\\Small-Basic-Extension\\src\\smallbasic_candidates.json"

# 데이터셋 경로
SOURCE_DIR = ".\\dataset\\sources"
ANSWER_DIR = ".\\dataset\\answers"

# 리포트 저장 경로 (폴더)
REPORT_DIR = ".\\reports"
FILE_REPORT_NAME = "1_file_performance.txt"
RANK_REPORT_NAME = "2_rank_distribution.txt"

# [제한] 분석할 최대 순위
MAX_RANK_CHECK = 20
# ==============================================================================

class FileReporter:
    def __init__(self):
        self.db = self.load_json(DB_PATH)
        
        # 통계 변수들
        self.rank_stats = defaultdict(int)
        self.out_of_range_count = 0
        self.global_queries = 0
        self.global_files = 0
        
        # 파일별 리포트 데이터
        self.file_reports = []
        
        # 리포트 폴더 생성
        if not os.path.exists(REPORT_DIR):
            os.makedirs(REPORT_DIR)

    def load_json(self, path):
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def run_cpp_batch(self, target_file):
        cmd = [EXE_PATH, "smallbasic", DLL_PATH, target_file, "--batch"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
            parsed_data = {}
            is_capturing = False
            for line in result.stdout.splitlines():
                line = line.strip()
                if "@@BATCH_START@@" in line:
                    is_capturing = True
                    continue
                if "@@BATCH_END@@" in line:
                    break
                if is_capturing and "|" in line:
                    try:
                        loc, states_str = line.split("|")
                        states = list(map(int, states_str.strip().split()))
                        parsed_data[loc.strip()] = states
                    except:
                        continue
            return parsed_data
        except:
            return {}

    def predict(self, states):
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

    def evaluate_file(self, sb_file):
        filename = os.path.basename(sb_file)
        json_name = filename.replace(".sb", ".json")
        json_path = os.path.join(ANSWER_DIR, json_name)

        if not os.path.exists(json_path):
            return

        answers = self.load_json(json_path)
        preds = self.run_cpp_batch(sb_file)

        file_query_count = 0
        file_top1_count = 0

        for loc, data in answers.items():
            if loc not in preds:
                self.out_of_range_count += 1
                self.global_queries += 1
                file_query_count += 1
                continue

            ground_truth = data.get("candidate", "")
            if not ground_truth: continue

            states = preds[loc]
            candidates = self.predict(states)
            rank = self.get_rank(candidates, ground_truth)

            self.global_queries += 1
            if 1 <= rank <= MAX_RANK_CHECK:
                self.rank_stats[rank] += 1
            else:
                self.out_of_range_count += 1

            file_query_count += 1
            if rank == 1:
                file_top1_count += 1

        self.global_files += 1
        self.file_reports.append({
            "name": filename,
            "total": file_query_count,
            "top1": file_top1_count
        })

    # ==========================================================================
    # [NEW] 파일 1: 파일별 성능 요약 저장
    # ==========================================================================
    def save_file_performance_report(self):
        output_path = os.path.join(REPORT_DIR, FILE_REPORT_NAME)
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("="*80 + "\n")
            f.write(f" PER-FILE PERFORMANCE SUMMARY\n")
            f.write("="*80 + "\n")
            f.write(f"{'File Name':<30} | {'Queries':<8} | {'Top-1 Acc':<10}\n")
            f.write("-" * 80 + "\n")

            for report in self.file_reports:
                total = report["total"]
                top1 = report["top1"]
                acc = (top1 / total * 100) if total > 0 else 0.0
                f.write(f"{report['name']:<30} | {total:<8} | {acc:.2f}%\n")
            
            f.write("-" * 80 + "\n")
            f.write(f"Total Files Processed: {self.global_files}\n")

        print(f"[Saved] File Report -> {output_path}")

    # ==========================================================================
    # [NEW] 파일 2: 전체 순위 분포 저장
    # ==========================================================================
    def save_rank_distribution_report(self):
        output_path = os.path.join(REPORT_DIR, RANK_REPORT_NAME)
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("="*80 + "\n")
            f.write(f" GLOBAL RANK DISTRIBUTION (Max Rank: {MAX_RANK_CHECK})\n")
            f.write("="*80 + "\n")
            
            if self.global_queries == 0:
                f.write("No queries found.\n")
                return

            f.write(f" Total Files   : {self.global_files}\n")
            f.write(f" Total Queries : {self.global_queries}\n")
            f.write("-" * 80 + "\n")
            f.write(f" {'Rank':<6} | {'Count':<10} | {'Share (%)':<10} | {'Cumulative (%)':<15}\n")
            f.write("-" * 80 + "\n")

            cumulative_count = 0
            
            # 1위 ~ 20위
            for r in range(1, MAX_RANK_CHECK + 1):
                count = self.rank_stats[r]
                cumulative_count += count
                
                share_pct = (count / self.global_queries) * 100
                cum_pct = (cumulative_count / self.global_queries) * 100
                
                # 텍스트 파일에서도 그래프 효과 유지
                bar_len = int(share_pct / 2)
                bar = "#" * bar_len # 텍스트 파일 호환성을 위해 # 사용
                
                f.write(f" {r:<6} | {count:<10} | {share_pct:6.2f}%    | {cum_pct:13.2f}%  {bar}\n")

            f.write("-" * 80 + "\n")
            
            # 20위 밖 (Out)
            out_share = (self.out_of_range_count / self.global_queries) * 100
            f.write(f" {'Out':<6} | {self.out_of_range_count:<10} | {out_share:6.2f}%    | {'-':<15}\n")
            f.write("="*80 + "\n")

        print(f"[Saved] Rank Report -> {output_path}")

    def run(self):
        files = glob.glob(os.path.join(SOURCE_DIR, "*.sb"))
        print(f"[*] Found {len(files)} files. Analyzing...")
        
        start = time.time()
        for f in files:
            print(f" -> Processing: {os.path.basename(f)}...", end="\r")
            self.evaluate_file(f)
        
        elapsed = time.time() - start
        print(f"\n[*] Analysis Complete in {elapsed:.2f} sec.\n")
        
        # 파일 저장 함수 호출
        self.save_file_performance_report()
        self.save_rank_distribution_report()

if __name__ == "__main__":
    reporter = FileReporter()
    reporter.run()