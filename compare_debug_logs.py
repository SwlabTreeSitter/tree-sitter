import os
import glob
import csv
import re

# =================[ 경로 설정 ]=================

# V1 로그 폴더 (Batch Mode 결과)
DIR_V1 = "/home/hyeonjin/PL/tree-sitter/reports/smallbasic/debug_states_v1"

# V2 로그 폴더 (Iterative Mode 결과)
DIR_V2 = "/home/hyeonjin/PL/tree-sitter/reports/smallbasic/debug_states_v2"

# 비교 결과 저장 경로
OUTPUT_DIR = "/home/hyeonjin/PL/tree-sitter/reports/smallbasic"
OUTPUT_FILE = "comparison_v1_vs_v2.csv"

# =================================================

def load_csv_data(filepath):
    """
    CSV 파일을 읽어서 Dictionary 형태로 반환
    Key: Location ("Row,Col")
    Value: { "truth": str, "states": str, "rank": str }
    """
    data = {}
    if not os.path.exists(filepath):
        return data
    
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None) # 헤더 건너뛰기
        
        for row in reader:
            if not row: continue
            # CSV 포맷: Location, Ground_Truth, State_List, Rank
            loc = row[0].strip()
            truth = row[1].strip()
            states = row[2].strip()
            rank = row[3].strip()
            
            data[loc] = {
                "truth": truth,
                "states": states,
                "rank": rank
            }
    return data

def main():
    if not os.path.exists(DIR_V1) or not os.path.exists(DIR_V2):
        print(f"[Error] Input directories not found.")
        print(f" V1: {DIR_V1}")
        print(f" V2: {DIR_V2}")
        return

    # 결과 CSV 생성
    output_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)
    
    print(f"[*] Starting comparison...")
    print(f" -> V1 Source: {DIR_V1}")
    print(f" -> V2 Source: {DIR_V2}")
    print(f" -> Output:    {output_path}")

    # V1 폴더 내의 모든 csv 파일 찾기
    v1_files = glob.glob(os.path.join(DIR_V1, "*_v1.csv"))
    
    total_files = 0
    total_mismatches = 0

    with open(output_path, "w", newline="", encoding="utf-8") as out_f:
        writer = csv.writer(out_f)
        # 헤더 작성
        writer.writerow([
            "File Name", 
            "Location", 
            "Ground Truth", 
            "Match?",         # State List 일치 여부
            "V1 State List",  # Batch
            "V2 State List",  # Iterative
            "V1 Rank", 
            "V2 Rank",
            "Rank Diff"       # V2 - V1 (양수면 V2가 더 못함, 음수면 V2가 더 잘함)
        ])

        for f1_path in v1_files:
            total_files += 1
            filename_v1 = os.path.basename(f1_path)
            
            # 파일명 매핑: test.sb_v1.csv -> test.sb_v2.csv
            filename_base = filename_v1.replace("_v1.csv", "")
            filename_v2 = f"{filename_base}_v2.csv"
            f2_path = os.path.join(DIR_V2, filename_v2)

            # 데이터 로드
            data_v1 = load_csv_data(f1_path)
            data_v2 = load_csv_data(f2_path)

            # 비교할 모든 위치(Location) 수집 (합집합)
            all_locations = set(data_v1.keys()) | set(data_v2.keys())
            
            # 위치 정렬 (Row, Col 순서)
            # "1,10"과 "2,1" 정렬을 위해 숫자 변환 필요
            sorted_locs = sorted(list(all_locations), key=lambda x: list(map(int, x.split(','))) if ',' in x else [99999,99999])

            for loc in sorted_locs:
                info_v1 = data_v1.get(loc, {"truth": "-", "states": "MISSING", "rank": "0"})
                info_v2 = data_v2.get(loc, {"truth": "-", "states": "MISSING", "rank": "0"})

                # 공통 정보 (Ground Truth는 양쪽 다 동일해야 함, 없으면 있는 쪽 사용)
                ground_truth = info_v1["truth"] if info_v1["truth"] != "-" else info_v2["truth"]
                
                states_v1 = info_v1["states"]
                states_v2 = info_v2["states"]
                
                rank_v1 = int(info_v1["rank"])
                rank_v2 = int(info_v2["rank"])

                # [비교 로직] State List가 문자열적으로 완전히 동일한가?
                is_match = (states_v1 == states_v2)
                match_str = "SAME" if is_match else "DIFF"

                if not is_match:
                    total_mismatches += 1

                # Rank 차이 계산
                rank_diff = rank_v2 - rank_v1

                writer.writerow([
                    filename_base,
                    loc,
                    ground_truth,
                    match_str,
                    states_v1,
                    states_v2,
                    rank_v1,
                    rank_v2,
                    rank_diff
                ])
            
            print(f" -> Processed: {filename_base}")

    print(f"\n[*] Comparison Complete.")
    print(f" -> Total Files: {total_files}")
    print(f" -> Total Mismatched Rows: {total_mismatches}")
    print(f" -> Report Saved: {output_path}")

if __name__ == "__main__":
    main()