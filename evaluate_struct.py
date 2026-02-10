import sys
import os
import glob
import json
import subprocess
import time
import csv
from collections import defaultdict

# =================[ 리눅스 경로 설정 ]=================

EXE_PATH = "/home/hyeonjin/PL/tree-sitter/TreeSitterCutFile.exe"
LIB_PATH = "/home/hyeonjin/PL/tree-sitter-smallbasic/smallbasic.so"
DB_PATH = "/home/hyeonjin/PL/extension/small-basic-extension/src/smallbasic_candidates.json"

# 데이터셋 경로
SOURCE_DIR = "/home/hyeonjin/PL/codecompletion_benchmarks/smallbasic/TEST_BENCH"
ANSWER_DIR = "/home/hyeonjin/PL/tree-sitter/reports/smallbasic"

# 리포트 저장 경로 (폴더)
REPORT_DIR = "/home/hyeonjin/PL/tree-sitter/reports/smallbasic"
FILE_REPORT_NAME = "sb_file_performance.txt"
RANK_REPORT_NAME = "sb_rank_distribution.txt"

# [제한] 분석할 최대 순위
MAX_CANDIDATE_LIST_SIZE = 20
MAX_RANK_CHECK = 20 

# =========================================================

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

    # [helper] 파일 내 모든 커서 위치에서의 컨버전 결과를 반환
    def run_cpp_batch(self, target_file):
        cmd = [EXE_PATH, "smallbasic", LIB_PATH, target_file, "--batch"]
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

    # [helper] 컨버전 결과로 DB 조회하여 구조적 후보 추천 목록 반환
    def lookupDB(self, states):
        merged_map = defaultdict(int)
        for state in states:
            s_key = str(state)
            if s_key in self.db:
                for item in self.db[s_key]:
                    merged_map[item['key']] += item['value']
                    
        sorted_result = sorted(merged_map.items(), key=lambda x: x[1], reverse=True)
        return sorted_result

    # [helper] 정답(ground_truth)이 구조적 후보 추천 목록에서 몇번째인지 계산
    def get_rank(self, candidates, ground_truth):
        gt_clean = ground_truth.replace(" ", "")
        print(f"    [Rank Check] Target: {gt_clean}")
        for rank, (key, val) in enumerate(candidates, 1):
            key_clean = key.replace(" ", "") 
            if key_clean == gt_clean:
                print(f"    [Match !!!!!] Target: {gt_clean} == DB: {key_clean} ({rank})")
                return rank
        print(f"    [Fail] Target not found in top {len(candidates)}.")
        return 0

    # [main] 단일 파일 평가
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
        file_top3_count = 0
        file_top5_count = 0
        file_top10_count = 0
        file_top20_count = 0

        # 파서의 결과 { "1,1": [states], ... }를 기준으로 루프 실행
        for loc, states in preds.items():
            
            # DB 조회
            full_candidates = self.lookupDB(states)
            top_candidates = full_candidates[:MAX_CANDIDATE_LIST_SIZE]

            # 정답 파일 조회
            if loc not in answers: continue
            
            ground_truth_data = answers[loc]
            ground_truth = ground_truth_data.get("candidate", "")
            gt_state_id = ground_truth_data.get("state_id", -1)

            if not ground_truth: continue

            # 순위 확인
            rank = self.get_rank(top_candidates, ground_truth)

            # 통계 집계
            self.global_queries += 1
            file_query_count += 1
            
            if rank > 0:
                self.rank_stats[rank] += 1
                if rank == 1: file_top1_count += 1
                if 1 <= rank <= 3: file_top3_count += 1
                if 1 <= rank <= 5: file_top5_count += 1
                if 1 <= rank <= 10: file_top10_count += 1
                if 1 <= rank <= 20: file_top20_count += 1
            else:
                self.out_of_range_count += 1

        self.global_files += 1
        self.file_reports.append({
            "name": filename,
            "total": file_query_count,
            "top1": file_top1_count,
            "top3": file_top3_count,
            "top5": file_top5_count,
            "top10": file_top10_count,
            "top20": file_top20_count
        })


    # ==========================================================================
    # 파일 1: 파일별 성능 요약 저장 (TXT + CSV)
    # ==========================================================================
    def save_file_performance_report(self):
        # 1. TXT 리포트 저장 (기존 로직 유지)
        txt_path = os.path.join(REPORT_DIR, FILE_REPORT_NAME)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("="*120 + "\n")
            f.write(f" PER-FILE PERFORMANCE SUMMARY\n")
            f.write("="*120 + "\n")
            f.write(f"{'File Name':<30} | {'Queries':<8} | {'Top-1':<8} | {'Top-3':<8} | {'Top-5':<8} | {'Top-10':<8} | {'Top-20':<8}\n")
            f.write("-" * 120 + "\n")

            for report in self.file_reports:
                total = report["total"]
                acc1 = (report["top1"] / total * 100) if total > 0 else 0.0
                acc3 = (report["top3"] / total * 100) if total > 0 else 0.0
                acc5 = (report["top5"] / total * 100) if total > 0 else 0.0
                acc10 = (report["top10"] / total * 100) if total > 0 else 0.0
                acc20 = (report["top20"] / total * 100) if total > 0 else 0.0

                f.write(f"{report['name']:<30} | {total:<8} | {acc1:6.2f}% | {acc3:6.2f}% | {acc5:6.2f}% | {acc10:6.2f}% | {acc20:6.2f}%\n")
            
            f.write("-" * 120 + "\n")
            f.write(f"Total Files Processed: {self.global_files}\n")
        
        print(f"[Saved] File Report (TXT) -> {txt_path}")

        # 2. CSV 리포트 저장 (추가된 로직)
        csv_path = os.path.join(REPORT_DIR, "sb_file_performance.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            # 헤더 작성
            writer.writerow(["File Name", "Total Queries", "Top-1 Acc (%)", "Top-3 Acc (%)", "Top-5 Acc (%)", "Top-10 Acc (%)", "Top-20 Acc (%)"])
            
            # 데이터 작성
            for report in self.file_reports:
                total = report["total"]
                acc1 = (report["top1"] / total * 100) if total > 0 else 0.0
                acc3 = (report["top3"] / total * 100) if total > 0 else 0.0
                acc5 = (report["top5"] / total * 100) if total > 0 else 0.0
                acc10 = (report["top10"] / total * 100) if total > 0 else 0.0
                acc20 = (report["top20"] / total * 100) if total > 0 else 0.0
                
                writer.writerow([report['name'], total, round(acc1, 2), round(acc3, 2), round(acc5, 2), round(acc10, 2), round(acc20, 2)])

        print(f"[Saved] File Report (CSV) -> {csv_path}")

    # ==========================================================================
    # 파일 2: 전체 순위 분포 저장 (TXT + CSV)
    # ==========================================================================
    def save_rank_distribution_report(self):
        # 1. TXT 리포트 저장 (기존 로직 유지)
        txt_path = os.path.join(REPORT_DIR, RANK_REPORT_NAME)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("="*80 + "\n")
            f.write(f" GLOBAL RANK DISTRIBUTION (Max Rank: {MAX_RANK_CHECK})\n")
            f.write("="*80 + "\n")
            
            if self.global_queries == 0:
                f.write("No queries found.\n")
            else:
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
                    bar_len = int(share_pct / 2)
                    bar = "#" * bar_len
                    
                    f.write(f" {r:<6} | {count:<10} | {share_pct:6.2f}%    | {cum_pct:13.2f}%  {bar}\n")

                f.write("-" * 80 + "\n")
                # Out
                out_share = (self.out_of_range_count / self.global_queries) * 100
                f.write(f" {'Out':<6} | {self.out_of_range_count:<10} | {out_share:6.2f}%    | {'-':<15}\n")
                f.write("="*80 + "\n")

        print(f"[Saved] Rank Report (TXT) -> {txt_path}")

        # 2. CSV 리포트 저장 (추가된 로직)
        if self.global_queries > 0:
            csv_path = os.path.join(REPORT_DIR, "sb_rank_distribution.csv")
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                # 헤더 작성
                writer.writerow(["Rank", "Count", "Share (%)", "Cumulative (%)"])
                
                cumulative_count = 0
                
                # 1위 ~ 20위 데이터
                for r in range(1, MAX_RANK_CHECK + 1):
                    count = self.rank_stats[r]
                    cumulative_count += count
                    share_pct = (count / self.global_queries) * 100
                    cum_pct = (cumulative_count / self.global_queries) * 100
                    
                    writer.writerow([r, count, round(share_pct, 2), round(cum_pct, 2)])
                
                # Out 데이터
                out_share = (self.out_of_range_count / self.global_queries) * 100
                writer.writerow(["Out", self.out_of_range_count, round(out_share, 2), "-"])

            print(f"[Saved] Rank Report (CSV) -> {csv_path}")

            
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