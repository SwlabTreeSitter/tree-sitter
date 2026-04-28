#!/usr/bin/env python3
"""
LEARN 컬렉션 빈도수 통합 스크립트.
.data 파일들을 SQLite로 집계하여 candidates.json을 생성한다.

사용법: python3 to_json_aggregate.py <language>
  예: python3 to_json_aggregate.py c
      python3 to_json_aggregate.py haskell
"""

import os
import sys
import glob
import sqlite3
import json

# =================[ 경로 설정 ]=================
ROOT = "/home/hyeonjin/PL"
EXT_DIR = os.path.join(ROOT, "code-completion-extension")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 to_json_aggregate.py <language>")
        sys.exit(1)

    lang = sys.argv[1]

    input_dir = os.path.join(ROOT, "benchmarks_collection", lang, "LEARN_data")
    output_file = os.path.join(EXT_DIR, "resources", lang, "candidates.json")
    temp_db_file = f"temp_aggregation_{lang}.db"

    # 0. 기존 결과 파일 삭제
    if os.path.exists(output_file):
        try:
            os.remove(output_file)
            print(f"[Info] Removed existing output file: {output_file}")
        except OSError as e:
            print(f"[Error] Failed to remove output file: {e}")
            return

    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    # 1. 파일 확인
    data_files = glob.glob(os.path.join(input_dir, "*.data"))
    total_files = len(data_files)

    if total_files == 0:
        print(f"[Error] No .data files found in {input_dir}")
        return

    print(f"[*] Found {total_files} files. Starting SQLite aggregation...")

    # 2. SQLite DB 준비
    if os.path.exists(temp_db_file):
        os.remove(temp_db_file)

    conn = sqlite3.connect(temp_db_file)
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

    # 3. 데이터 집계
    count_processed = 0
    sql_update = "UPDATE stats SET count = count + 1 WHERE state = ? AND pattern = ?"
    sql_insert = "INSERT INTO stats (state, pattern, count) VALUES (?, ?, 1)"

    for file_path in data_files:
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for raw in f:
                    # 줄바꿈만 제거하고 들여쓰기는 보존한다.
                    # 컬렉션 라이터가 multi-line 비단말 노드의 source 를 escape 없이 덤프하므로
                    # .data 안에 raw 소스 라인이 섞여 들어올 수 있다. 그 라인들은 들여쓰기를 갖고 있어
                    # 컬럼 0 이 숫자가 아니므로 여기서 자동 거부된다.
                    line = raw.rstrip("\r\n")
                    if not line or not line[0].isdigit():
                        continue

                    parts = line.split(maxsplit=1)
                    state_id = int(parts[0])
                    pattern = parts[1].strip() if len(parts) > 1 else ""

                    cursor.execute(sql_update, (state_id, pattern))
                    if cursor.rowcount == 0:
                        cursor.execute(sql_insert, (state_id, pattern))

            if count_processed % 100 == 0:
                conn.commit()

        except Exception:
            pass

        count_processed += 1

    conn.commit()
    print("[*] Aggregation finished. Writing directly to JSON...")

    # 4. JSON 파일 작성
    try:
        with open(output_file, 'w', encoding='utf-8') as outfile:
            outfile.write("{\n")

            cursor.execute('SELECT state, pattern, count FROM stats ORDER BY state ASC, count DESC')

            current_state = None
            current_patterns = []
            is_first_state = True

            for row in cursor:
                state, pattern, count = row

                if state != current_state:
                    if current_state is not None:
                        if not is_first_state:
                            outfile.write(",\n")
                        outfile.write(f'  "{current_state}": ')
                        json.dump(current_patterns, outfile)
                        is_first_state = False
                        current_patterns = []

                    current_state = state

                current_patterns.append({
                    "key": pattern,
                    "value": count
                })

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
    if os.path.exists(temp_db_file):
        os.remove(temp_db_file)

    print(f"[*] Done! JSON saved to: {output_file}")


if __name__ == "__main__":
    main()
