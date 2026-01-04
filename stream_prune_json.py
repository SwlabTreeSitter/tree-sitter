import json
import os
import sys

# =================[ 설정 ]=================
# 1. 입력: 거대한 txt 파일 경로
INPUT_TXT = "/home/hyeonjin/PL/tree-sitter/smallbasic-syntax-completion-candidates-results.txt"

# 2. 출력: 다이어트된 json 파일 경로
OUTPUT_JSON = "/home/hyeonjin/PL/tree-sitter/smallbasic_candidates_small.json"

# 3. 각 State별 남길 최대 후보 개수 (Pruning)
TOP_K = 10
# ==========================================

def format_pattern_clean(raw_pattern_inside_brackets):
    # "[ID = Expr]" -> "[ID, =, Expr]"
    tokens = raw_pattern_inside_brackets.split()
    return "[" + ", ".join(tokens) + "]"

def main():
    if not os.path.exists(INPUT_TXT):
        print(f"[Error] File not found: {INPUT_TXT}")
        return

    print(f"[*] Starting Top-{TOP_K} Pruning & Conversion...")
    print(f"    Input: {INPUT_TXT}")
    print(f"    Output: {OUTPUT_JSON}")

    try:
        with open(INPUT_TXT, 'r', encoding='utf-8') as infile, \
             open(OUTPUT_JSON, 'w', encoding='utf-8') as outfile:
            
            # JSON 시작
            outfile.write("{\n")
            
            current_state = None
            current_patterns = []
            is_first_state = True
            
            # 현재 State에서 몇 개나 담았는지 카운트
            patterns_in_current_state = 0
            
            line_count = 0

            for line in infile:
                line = line.strip()
                if not line: continue
                
                # 1. State 헤더 파싱
                if line.startswith("State"):
                    # 이전 State 기록 (버퍼 비우기)
                    if current_state is not None:
                        if not is_first_state:
                            outfile.write(",\n")
                        
                        outfile.write(f'  "{current_state}": ')
                        json.dump(current_patterns, outfile)
                        
                        is_first_state = False
                        current_patterns = [] # 메모리 초기화
                        patterns_in_current_state = 0 # 카운터 초기화

                    try:
                        current_state = line.split()[1]
                    except IndexError:
                        pass
                    
                    if line_count % 10000 == 0:
                        print(f"   Processing State {current_state}...")
                    line_count += 1
                    continue

                # 2. 패턴 데이터 파싱
                # 이미 TXT 파일이 빈도순으로 정렬되어 있다고 가정 (SQLite 쿼리 결과이므로)
                # 따라서 단순히 앞에서부터 TOP_K 개만 담고 나머지는 무시하면 됩니다.
                if current_state is not None and ":" in line:
                    # 이미 목표 개수를 채웠다면, 다음 State가 나올 때까지 읽지 않고 건너뜀 (속도 향상 & 메모리 절약)
                    if patterns_in_current_state >= TOP_K:
                        continue

                    try:
                        pattern_part, count_part = line.rsplit(":", 1)
                        pattern_part = pattern_part.strip()
                        count = int(count_part.strip())

                        if pattern_part.startswith("[") and pattern_part.endswith("]"):
                            pattern_inner = pattern_part[1:-1].strip()
                        else:
                            pattern_inner = pattern_part
                        
                        formatted_key = format_pattern_clean(pattern_inner)
                        
                        current_patterns.append({
                            "key": formatted_key,
                            "value": count
                        })
                        
                        patterns_in_current_state += 1
                        
                    except ValueError:
                        pass

            # 3. 마지막 State 처리
            if current_state is not None and current_patterns:
                if not is_first_state:
                    outfile.write(",\n")
                outfile.write(f'  "{current_state}": ')
                json.dump(current_patterns, outfile)

            # JSON 끝
            outfile.write("\n}")

        # 용량 확인
        size_mb = os.path.getsize(OUTPUT_JSON) / (1024 * 1024)
        print(f"\n[*] Done! Slim JSON saved ({size_mb:.2f} MB).")

    except Exception as e:
        print(f"\n[Error] {e}")

if __name__ == "__main__":
    main()