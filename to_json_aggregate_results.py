# [Linux] DB 구축 위한 LEARN 컬렉션 빈도수 통합 스크립트
# For all languages (by 경로 수정)
#   1) .(lang) -> .data
#   2) .data   -> .json  <-- here


import os
import glob
import sqlite3
import json

# =================[ 설정 ]=================
# 다른 언어 작업 시 여기 경로만 수정
INPUT_DIR = "/home/hyeonjin/PL/benchmarks_collection/smallbasic/LEARN_BENCH_data2"
OUTPUT_FILE = "/home/hyeonjin/PL/extension/small-basic-extension/src/smallbasic_candidates2.json"
# INPUT_DIR =  "/home/hyeonjin/PL/benchmarks_collection/c11/LEARN_BENCH_data"
# OUTPUT_FILE = "/home/hyeonjin/PL/extension/small-basic-extension/src/c11_candidates.json"
TEMP_DB_FILE = "temp_aggregation.db" 
# ==========================================

def format_pattern_clean(raw_pattern):
    """
    입력: "= ID . ID"
    출력: "[=, ID, ., ID]"
    """
    tokens = raw_pattern.split()
    return "[" + ", ".join(tokens) + "]"

def main():
    # 0. 기존 결과 파일 삭제 (Clean Start)
    if os.path.exists(OUTPUT_FILE):
        try:
            os.remove(OUTPUT_FILE)
            print(f"[Info] Removed existing output file: {OUTPUT_FILE}")
        except OSError as e:
            print(f"[Error] Failed to remove output file: {e}")
            return

    # 1. 파일 확인
    data_files = glob.glob(os.path.join(INPUT_DIR, "*.data"))
    total_files = len(data_files)
    
    if total_files == 0:
        print(f"[Error] No .data files found in {INPUT_DIR}")
        return

    print(f"[*] Found {total_files} files. Starting SQLite aggregation...")

    # 2. SQLite DB 준비 (메모리 부족 방지)
    if os.path.exists(TEMP_DB_FILE):
        os.remove(TEMP_DB_FILE)
        
    conn = sqlite3.connect(TEMP_DB_FILE)
    cursor = conn.cursor()
    cursor.execute('PRAGMA synchronous = OFF')
    cursor.execute('PRAGMA journal_mode = MEMORY')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stats (
            state INTEGER,
            pattern TEXT,
            count INTEGER,
            PRIMARY KEY (state, pattern)
        )
    ''')
    conn.commit()

    # 3. 데이터 집계 (Data -> SQLite)
    count_processed = 0
    # (state, pattern)이 이미 존재하면 count를 1 증가시킴 (누적)
    sql_update = "UPDATE stats SET count = count + 1 WHERE state = ? AND pattern = ?"
    # (state, pattern)이 처음 등장하면 count를 1로 생성
    sql_insert = "INSERT INTO stats (state, pattern, count) VALUES (?, ?, 1)"

    for file_path in data_files:
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if not line: continue

                    parts = line.split(maxsplit=1)
                    if not parts[0].isdigit():
                        continue
                        
                    state_id = int(parts[0])
                    pattern = parts[1].strip() if len(parts) > 1 else ""

                    cursor.execute(sql_update, (state_id, pattern))     # 1. 먼저 업데이트 시도
                    if cursor.rowcount == 0:                            # 2. 업데이트된 행이 없으면(처음 본 키면)
                        cursor.execute(sql_insert, (state_id, pattern)) # 3. 새로 추가
            
            if count_processed % 100 == 0:
                conn.commit()
                # print(f"   Processed {count_processed}/{total_files} files...")
                
        except Exception:
            pass
        
        count_processed += 1

    conn.commit()
    print("[*] Aggregation finished. Writing directly to JSON...")

    # 4. JSON 파일 작성 (SQLite -> JSON Streaming)
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as outfile:
            outfile.write("{\n")
            
            # 쿼리: State 오름차순, 빈도수 내림차순
            cursor.execute('SELECT state, pattern, count FROM stats ORDER BY state ASC, count DESC')
            
            current_state = None
            current_patterns = []
            is_first_state = True
            
            for row in cursor:
                state, pattern, count = row
                
                # State가 바뀌는 시점에 이전 데이터 기록
                # -------------------------------------------------------------------------
                #  Iter |  Row 데이터 (State, Pattern, Count) |  동작 (Action)
                # -------------------------------------------------------------------------
                #   1   |  (0, "ID = Expr", 100)              |  State 0 수집 중... (Buffer)
                #   2   |  (0, "GraphicsWindow...", 50)       |  State 0 수집 중... (Buffer)
                #   3   |  (5, "If Expr Then", 30)            |  State 0 != 5 감지!
                #       |                                     |  -> 모아둔 0번 데이터를 JSON에 기록
                #       |                                     |  -> State 5 수집 시작
                # -------------------------------------------------------------------------
                if state != current_state:
                    if current_state is not None:
                        if not is_first_state:
                            outfile.write(",\n")
                        
                        outfile.write(f'  "{current_state}": ')
                        json.dump(current_patterns, outfile)
                        
                        is_first_state = False
                        current_patterns = [] # 메모리 비우기

                    current_state = state
                
                # 패턴 포맷팅 및 리스트 추가
                # "ID = Expr" -> "[ID, =, Expr]"
                # formatted_key = format_pattern_clean(pattern)
                current_patterns.append({
                    "key": pattern, # formatted_key,
                    "value": count
                })

            # 마지막 State 처리
            if current_state is not None and current_patterns:
                if not is_first_state:
                    outfile.write(",\n")
                outfile.write(f'  "{current_state}": ')
                json.dump(current_patterns, outfile)

            outfile.write("\n}")
            
    except Exception as e:
        print(f"[Error] Writing JSON: {e}")

    # 5. 뒷정리
    conn.close()
    if os.path.exists(TEMP_DB_FILE):
        os.remove(TEMP_DB_FILE)

    print(f"[*] Done! JSON saved to: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()