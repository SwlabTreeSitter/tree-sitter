import os
import glob
import sqlite3
import json

# =================[ 설정 ]=================
# 1. 입력 경로 (다른 언어 작업 시 수정)
INPUT_DIR = "/home/hyeonjin/PL/benchmarks_collection/smallbasic/LEARN_BENCH_data"

# 2. 출력 경로 (최종적으로 나올 가벼운 JSON 파일)
OUTPUT_FILE = "/home/hyeonjin/PL/tree-sitter/smallbasic_candidates_final.json"

# 3. 임시 DB 파일 (작업 후 자동 삭제됨)
TEMP_DB_FILE = "temp_aggregation.db" 

# 4. 각 State별 남길 최대 후보 개수 (Pruning)
TOP_K = 10
# ==========================================

def format_pattern_clean(raw_pattern):
    """
    입력: "= ID . ID"
    출력: "[=, ID, ., ID]"
    """
    tokens = raw_pattern.split()
    return "[" + ", ".join(tokens) + "]"

def main():
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
    # 속도 최적화 옵션
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

    # 3. 데이터 집계 (Data Files -> SQLite)
    count_processed = 0
    sql_update = "UPDATE stats SET count = count + 1 WHERE state = ? AND pattern = ?"
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

                    # DB에 넣기 (이미 있으면 카운트 증가, 없으면 추가)
                    cursor.execute(sql_update, (state_id, pattern))
                    if cursor.rowcount == 0:
                        cursor.execute(sql_insert, (state_id, pattern))
            
            if count_processed % 100 == 0:
                conn.commit()
                # print(f"   Processed {count_processed}/{total_files} files...")
                
        except Exception:
            pass
        
        count_processed += 1

    conn.commit()
    print("[*] Aggregation finished. Pruning and writing to JSON...")

    # 4. JSON 파일 작성 (SQLite -> Pruning -> JSON)
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as outfile:
            outfile.write("{\n")
            
            # 중요: 빈도수 내림차순(DESC)으로 조회
            cursor.execute('SELECT state, pattern, count FROM stats ORDER BY state ASC, count DESC')
            
            current_state = None
            current_patterns = []
            is_first_state = True
            
            # 현재 State에 몇 개를 담았는지 체크
            patterns_in_current_state = 0
            
            for row in cursor:
                state, pattern, count = row
                
                # State가 바뀌는 시점 (이전 State 데이터 기록)
                if state != current_state:
                    if current_state is not None:
                        if not is_first_state:
                            outfile.write(",\n")
                        
                        outfile.write(f'  "{current_state}": ')
                        json.dump(current_patterns, outfile)
                        
                        is_first_state = False
                        current_patterns = [] 
                        patterns_in_current_state = 0 # 카운터 초기화

                    current_state = state
                
                # [핵심 변경 사항] 이미 TOP_K개를 채웠으면 더 담지 않고 건너뜀
                # DB에서 이미 정렬되어 나오므로, 뒤에 나오는 건 빈도수가 낮은 것들임
                if patterns_in_current_state >= TOP_K:
                    continue

                # 패턴 포맷팅 및 리스트 추가
                formatted_key = format_pattern_clean(pattern)
                current_patterns.append({
                    "key": formatted_key,
                    "value": count
                })
                patterns_in_current_state += 1

            # 마지막 State 처리
            if current_state is not None and current_patterns:
                if not is_first_state:
                    outfile.write(",\n")
                outfile.write(f'  "{current_state}": ')
                json.dump(current_patterns, outfile)

            outfile.write("\n}")
            
        # 결과 파일 크기 확인
        size_mb = os.path.getsize(OUTPUT_FILE) / (1024 * 1024)
        print(f"[*] Done! Slim JSON saved: {OUTPUT_FILE} ({size_mb:.2f} MB)")
            
    except Exception as e:
        print(f"[Error] Writing JSON: {e}")

    # 5. 뒷정리 (임시 DB 삭제)
    conn.close()
    if os.path.exists(TEMP_DB_FILE):
        os.remove(TEMP_DB_FILE)

if __name__ == "__main__":
    main()