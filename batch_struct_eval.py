# python batch_eval.py C:\PL\tree-sitter-smallbasic\SB_Sample1\01_HelloWorld.sb
import sys
import os
import json
import subprocess
import time
from collections import defaultdict

# ==============================================================================
# 1. C++ 실행 파일 경로
EXE_PATH = ".\\TreeSitterCutFile.exe" 

# 2. 언어 라이브러리 DLL 경로
DLL_PATH = ".\\smallbasic.dll"
"" 

# 3. 자동완성 후보 JSON DB 경로 (TypeScript 프로젝트에 있는 파일)
DB_PATH = "..\\moniExtension\\Small-Basic-Extension\\src\\smallbasic_candidates.json"
# ==============================================================================

def load_db():
    """
    JSON DB를 메모리에 로드합니다.
    """
    if not os.path.exists(DB_PATH):
        print(f"[Error] DB Not Found: {DB_PATH}")
        sys.exit(1)
        
    print(f"[*] Loading DB from: {DB_PATH}")
    with open(DB_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
        print(f"[*] DB Loaded. Total states: {len(data)}")
        return data

def run_cpp_batch(target_file):
    """
    C++ EXE를 '--batch' 모드로 실행하고, 
    모든 커서 위치의 상태 경로(State Path)를 파싱하여 딕셔너리로 반환합니다.
    
    Returns:
        dict: { "ROW,COL": [state_id, state_id, ...], ... }
    """
    # C++ 실행 명령어 구성
    cmd = [EXE_PATH, "smallbasic", DLL_PATH, target_file, "--batch"]
    
    print(f"[*] Running C++ Parser (Batch Mode)...")
    start_time = time.time()
    
    try:
        # 실행
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        
        # 출력 파싱 시작
        parsed_data = {}
        is_capturing = False
        
        # C++ 출력 포맷 가정:
        # @@BATCH_START@@
        # 1,1|51 29 65
        # 1,5|51 29 65 12
        # ...
        # @@BATCH_END@@
        
        for line in result.stdout.splitlines():
            line = line.strip()
            
            if "@@BATCH_START@@" in line:
                is_capturing = True
                continue
            if "@@BATCH_END@@" in line:
                break
                
            if is_capturing and "|" in line:
                try:
                    # "1,1|51 29 65" -> loc="1,1", states="51 29 65"
                    loc_part, states_part = line.split("|")
                    
                    # 문자열을 정수 리스트로 변환
                    states = list(map(int, states_part.strip().split()))
                    
                    parsed_data[loc_part.strip()] = states
                except ValueError:
                    continue # 파싱 에러나면 해당 라인 스킵

        elapsed = time.time() - start_time
        print(f"[*] Batch Process Finished in {elapsed:.4f} sec.")
        print(f"[*] Extracted {len(parsed_data)} cursor positions.")
        
        return parsed_data

    except Exception as e:
        print(f"[Error] Failed to run C++ parser: {e}")
        return {}

def aggregate_candidates(db, states):
    """
    [핵심 로직] TypeScript의 lookupDB와 동일한 로직
    - 여러 State에서 추천된 후보들을 합치고(Merge)
    - 중복된 후보는 빈도수(Value)를 합산(Sum)
    - 빈도수 내림차순 정렬
    """
    merged_map = defaultdict(int) # Key: Candidate String, Value: Frequency

    for state in states:
        state_key = str(state)
        
        # DB에 해당 상태가 있는지 확인
        if state_key in db:
            candidates = db[state_key]
            for item in candidates:
                # TypeScript: existing.value += item.value
                merged_map[item['key']] += item['value']

    # 리스트로 변환 및 정렬 (Value 내림차순)
    # 결과 예: [ ("ID = Expr", 50), ("Function", 30), ... ]
    sorted_result = sorted(merged_map.items(), key=lambda x: x[1], reverse=True)
    return sorted_result

def main():
    # 인자 확인
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <TargetFile.sb>")
        return

    target_file = sys.argv[1]
    if not os.path.exists(target_file):
        print(f"[Error] Target file not found: {target_file}")
        return

    # 1. DB 로드 (1회)
    db = load_db()

    # 2. C++ 일괄 실행 및 데이터 획득 (1회)
    #    파일 전체의 모든 위치 정보를 한방에 가져옴
    all_positions_data = run_cpp_batch(target_file)

    if not all_positions_data:
        print("[Warning] No data extracted from C++ parser.")
        return

    # 3. 순회 검증
    #    메모리에 있는 데이터를 루프 돌며 로직 검증
    print("\n" + "="*60)
    print(f" [REPORT] Analysis for: {os.path.basename(target_file)}")
    print("="*60)

    # (옵션) 너무 많으면 앞부분 10개만 출력하거나 특정 조건만 출력
    count = 0
    for loc, states in all_positions_data.items():
        count += 1
        
        # 로직 수행 (순수 파이썬 연산)
        candidates = aggregate_candidates(db, states)
        
        # 결과 출력
        top_candidate = candidates[0] if candidates else ("NO_CANDIDATE", 0)
        
        print(f"Loc [{loc}]")
        print(f"  - States: {states}")
        print(f"  - Top 1 : {top_candidate[0]} (Freq: {top_candidate[1]})")
        
        # 상세 후보 3개까지 보기
        if candidates:
            print(f"  - Others: {[c[0] for c in candidates[1:3]]}")
        print("-" * 40)

        # (테스트용) 5개까지만 출력하고 중단하려면 주석 해제
        # if count >= 5: break

if __name__ == "__main__":
    main()