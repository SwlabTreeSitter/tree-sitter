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
# (이전 단계에서 .data -> .json 변환이 완료되어 있어야 합니다)
ANSWER_DIR = "/home/hyeonjin/PL/tree-sitter/reports/smallbasic"

# 리포트 저장 경로
REPORT_DIR = "/home/hyeonjin/PL/tree-sitter/reports/smallbasic"

# DB 경로 (후보 추천용)
DB_PATH = "/home/hyeonjin/PL/code-completion-extension/resources/smallbasic/candidates.json"

# 평가 설정
MAX_CANDIDATE_LIST_SIZE = 20
MAX_RANK_CHECK = 20 

# =========================================================

class FileReporter:
    def __init__(self):
        self.db = self.load_json(DB_PATH)
        
        # 통계 변수
        self.rank_stats = defaultdict(int)
        self.beyond_top20_count = 0
        self.cpp_fail_count = 0
        self.global_queries = 0
        self.global_files = 0
        self.file_reports = []
        
        # 리포트 폴더 생성
        if not os.path.exists(REPORT_DIR):
            os.makedirs(REPORT_DIR)

    def load_json(self, path):
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # -------------------------------------------------------------------------
    # [핵심] 단일 위치 실행 함수 (Iterative Execution)
    # C++ 프로그램을 특정 Row, Col 좌표로 실행하여 예측값(State List)을 받아옴
    # -------------------------------------------------------------------------
    def run_cpp_at_position(self, target_file, row, col):
        # 명령어: EXE lang lib file row col 0(ConversionMode)
        cmd = [EXE_PATH, "smallbasic", LIB_PATH, target_file, str(row), str(col), "0"]
        
        try:
            # 프로세스 실행 (매번 실행하므로 오버헤드 있음)
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                encoding='utf-8',
                errors='replace' # 인코딩 에러 방지
            )
            
            if result.returncode != 0:
                # C++ 내부 에러 발생 시
                return []

            # 출력 파싱 (@@PREDICT: 태그 찾기)
            # for line in result.stdout.splitlines():
            #     if line.startswith("@@PREDICT:"):
            #         # "@@PREDICT: 188 51 ..." -> [188, 51, ...]
            #         raw_nums = line.replace("@@PREDICT:", "").strip()
            #         if not raw_nums: return []
            #         return list(map(int, raw_nums.split()))

            for line in result.stdout.splitlines():
                # "@@PREDICT:" 뒤에 오는 숫자와 공백들의 조합만 캡처
                match = re.search(r"@@PREDICT:\s*([\d\s]+)", line)
                
                if match:
                    raw_nums = match.group(1).strip()
                    if not raw_nums: 
                        return []
                        
                    # 방어 3: 혹시 모를 변환 에러를 대비한 개별 try-except
                    states = []
                    for num_str in raw_nums.split():
                        try:
                            states.append(int(num_str))
                        except ValueError:
                            pass # 숫자가 아닌 쓰레기값은 무시하고 계속 진행
                    
                    return states
            
            return [] # 태그를 못 찾음
            
        except Exception as e:
            print(f"[Error] Failed to parse output at {row},{col} - {e}")
            return []

    # [helper] DB Lookup
    def lookupDB(self, states):
        merged_map = defaultdict(int)
        for state in states:
            s_key = str(state)
            if s_key in self.db:
                for item in self.db[s_key]:
                    merged_map[item['key']] += item['value']
                    
        return sorted(merged_map.items(), key=lambda x: x[1], reverse=True)

    # [helper] Rank Calculation
    def get_rank(self, candidates, ground_truth):
        gt_clean = ground_truth.replace(" ", "")
        for rank, (key, val) in enumerate(candidates, 1):
            key_clean = key.replace(" ", "") 
            if key_clean == gt_clean:
                return rank
        return 0

    def save_debug_log(self, filename, log_data):
        # 저장 폴더: reports/smallbasic/debug_states_v2
        debug_dir = os.path.join(REPORT_DIR, "debug_states_v2")
        if not os.path.exists(debug_dir):
            os.makedirs(debug_dir)
        
        csv_path = os.path.join(debug_dir, f"{filename}_v2.csv")
        
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            # V1과 동일한 헤더 구조
            writer.writerow(["Location", "Ground_Truth", "State_List", "Rank"])
            writer.writerows(log_data)

    # -------------------------------------------------------------------------
    # [Main Logic] 파일 단위 평가
    # -------------------------------------------------------------------------
    def evaluate_file(self, sb_file):
        filename = os.path.basename(sb_file)
        json_name = filename.replace(".sb", ".json")
        json_path = os.path.join(ANSWER_DIR, json_name)

        # 정답지(.json)가 없으면 스킵
        if not os.path.exists(json_path):
            print(f" [Skip] No Ground Truth for {filename}")
            return

        # 정답지 로드 (Key: "Row,Col", Value: Ground Truth Info)
        answers = self.load_json(json_path)
        if not answers:
            return

        file_query_count = 0
        file_top1_count = 0
        file_top3_count = 0
        file_top5_count = 0
        file_top10_count = 0
        file_top20_count = 0

        # 로그 데이터 리스트
        debug_logs = []
        # 정렬하여 순회 (V1과 비교 쉽도록)
        sorted_locs = sorted(answers.keys(), key=lambda x: list(map(int, x.split(','))))

        # [Iterative Loop] 정답지의 모든 좌표에 대해 실행
        total_locations = len(answers)
        processed_locs = 0

        print(f" -> Analyzing {filename} ({total_locations} points)...")

        for loc_key, gt_data in answers.items():
            processed_locs += 1
            
            # 진행률 표시 (너무 자주 찍으면 느리므로 10개 단위)
            if processed_locs % 10 == 0:
                print(f"    Processing {processed_locs}/{total_locations}...", end="\r")

            # 1. 좌표 파싱 ("2,15" -> row=2, col=15)
            try:
                r_str, c_str = loc_key.split(",")
                row, col = int(r_str), int(c_str)
            except:
                continue

            # 2. 정답 데이터 확인
            ground_truth = gt_data.get("candidate", "")
            if not ground_truth: continue

            # 3. [핵심] C++ 실행 (단일 위치)
            predicted_states = self.run_cpp_at_position(sb_file, row, col)

            # State List 포맷팅
            if predicted_states:
                state_str = str(predicted_states) # 예: "[188, 51]"
            else:
                state_str = "FAIL" # C++ 실행 실패 또는 태그 없음

            # 순위 계산
            rank = 0
            if predicted_states:
                full_candidates = self.lookupDB(predicted_states)
                top_candidates = full_candidates[:MAX_CANDIDATE_LIST_SIZE]
                rank = self.get_rank(top_candidates, ground_truth)

            # 로그 저장
            debug_logs.append([loc_key, ground_truth, state_str, rank])

            # # 4. DB 조회 및 순위 계산
            # full_candidates = self.lookupDB(predicted_states)
            # top_candidates = full_candidates[:MAX_CANDIDATE_LIST_SIZE]
            
            # rank = self.get_rank(top_candidates, ground_truth)

            # 5. 통계 집계
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
            "name": filename,
            "total": file_query_count,
            "top1": file_top1_count,
            "top3": file_top3_count,
            "top5": file_top5_count,
            "top10": file_top10_count,
            "top20": file_top20_count
        })

        # [NEW] 로그 저장
        self.save_debug_log(filename, debug_logs)

    # ==========================================================================
    # 파일 1: 파일별 성능 요약 저장
    # ==========================================================================
    def save_file_performance_report(self):

        # CSV 리포트 저장
        csv_path = os.path.join(REPORT_DIR, "sb_file_performance_v2.csv")
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


    def run(self):
        files = glob.glob(os.path.join(SOURCE_DIR, "*.sb"))
        print(f"[*] Found {len(files)} files. Starting Iterative Analysis...")
        
        start = time.time()
        for f in files:
            self.evaluate_file(f)
        
        elapsed = time.time() - start
        print(f"\n[*] Analysis Complete in {elapsed:.2f} sec.")

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