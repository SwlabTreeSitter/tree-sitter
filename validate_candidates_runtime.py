#!/usr/bin/env python3
"""
validate_candidates_runtime.py

각 커서 위치에서 구조후보평가로 얻은 구조후보의 첫 토큰이
해당 위치에서 문법적으로 가능한지 실제 파싱으로 검증한다.

방법:
  1. debug_coverage CSV에서 커서 위치(byte offset)와 state 목록을 읽음
  2. 각 state의 구조후보 첫 토큰을 실제 텍스트로 변환
  3. source[0:cursor] + token_text 를 tree-sitter로 파싱
  4. 삽입 지점에 ERROR가 있으면 → 해당 토큰은 이 위치에서 문법적으로 불가능

사용법:
  python3 validate_candidates_runtime.py ruby
  python3 validate_candidates_runtime.py ruby --sample 100    # 100개 위치만 샘플링
  python3 validate_candidates_runtime.py ruby --file blanket   # 특정 파일만
"""

import sys
import os
import csv
import json
import ast
import subprocess
import tempfile
import re
from collections import defaultdict, Counter

TS_DIR = os.path.dirname(os.path.abspath(__file__))

LANG_CONFIGS = {
    "ruby": {
        "db":         "/home/hyeonjin/PL/code-completion-extension/resources/ruby/candidates.json",
        "src":        "/home/hyeonjin/PL/codecompletion_benchmarks/ruby/TEST",
        "report":     os.path.join(TS_DIR, "reports/ruby"),
        "grammar_dir": "/home/hyeonjin/PL/tree-sitter-ruby",
    },
}

# 구조후보 첫 토큰 → 실제 텍스트 매핑
TOKEN_TEXT_MAP = {
    # 심볼 이름 → 파싱 가능한 텍스트
    'identifier': 'x', 'constant': 'MyClass', 'instance_variable': '@x',
    'class_variable': '@@x', 'global_variable': '$x',
    'integer': '1', 'float': '1.0', 'complex': '1i', 'rational': '1r',
    'simple_symbol': ':foo', 'character': '?a',
    'heredoc_beginning': '<<~HEREDOC', 'string_content': 'hello',
    'heredoc_content': 'content', 'heredoc_end': 'HEREDOC',
    'escape_sequence': '\\n', 'hash_key_symbol': 'key:',
    '_line_break': '\n', '_terminator': '\n',
    '"': '"', "'": "'", '`': '`', ':"': ':"',
    '%w(': '%w(', '%i(': '%i(',
    'comment': '# comment',
    'identifier_suffix_token1': 'x?', 'constant_suffix_token1': 'Foo!',
    # non-terminal → 가장 단순한 terminal로 확장
    '_arg': 'x', '_argument': 'x', '_expression': 'x', '_statements': 'x',
    '_argument_list_with_trailing_comma': 'x', '_statements_repeat1': 'x',
    '_array_pattern_n': 'x', '_hash_pattern_body': 'key:', '_pattern_expr': 'x',
    '_identifier_suffix': '?', '_constant_suffix': '!',
    '_short_interpolation': '#',
    'encoding': '__ENCODING__', 'file': '__FILE__', 'line': '__LINE__',
    'keyword_pattern': 'key:', 'pair': 'key:',
    'pattern': 'x', 'i': 'i', 'r': 'r', 'ri': 'ri',
    '+@': '+@', '-@': '-@', '[]': '[]', '[]=': '[]=',
    'string_array_token1': ' ',
}

# 텍스트 변환 불가 (검증 스킵)
SKIP_TOKENS = {
    '_heredoc_body_start', 'block_body', 'body_statement',
    'case_repeat1', 'heredoc_body_repeat1',
}


def load_db(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def get_first_token_text(candidate_key):
    """구조후보의 첫 토큰을 실제 텍스트로 변환."""
    tokens = candidate_key.split()
    if not tokens:
        return None
    first = tokens[0]

    if first in SKIP_TOKENS:
        return None

    if first in TOKEN_TEXT_MAP:
        return TOKEN_TEXT_MAP[first]

    # 직접 사용 가능한 키워드/연산자 (영문자 또는 특수문자)
    # tree-sitter 심볼 이름이 곧 텍스트인 경우
    return first


def parse_and_check_error(source_bytes, insert_offset, token_text, grammar_dir):
    """source[0:insert_offset] + token_text를 파싱하여 삽입 지점에 ERROR가 있는지 확인."""
    modified = source_bytes[:insert_offset] + token_text.encode('utf-8')

    with tempfile.NamedTemporaryFile(suffix='.rb', delete=False, mode='wb') as f:
        f.write(modified)
        tmp_path = f.name

    try:
        result = subprocess.run(
            [os.path.join(TS_DIR, 'target/debug/tree-sitter'), 'parse', tmp_path, '--quiet'],
            capture_output=True, text=True, cwd=grammar_dir, timeout=10
        )
        output = result.stdout + result.stderr

        # tree-sitter parse --quiet: 에러가 있으면 출력에 (ERROR) 또는 에러 범위 표시
        # 반환코드 0 = 에러 없음, 1 = 에러 있음
        has_error = result.returncode != 0

        return has_error, output
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT"
    finally:
        os.unlink(tmp_path)


def find_source_file(src_dir, debug_csv_name):
    """debug CSV 이름에서 원본 소스 파일 경로를 역추적."""
    # debug CSV 이름: project_subdir_filename.csv
    # 원본: src_dir/project/subdir/filename
    rel = debug_csv_name.replace('.csv', '')
    # 가능한 경로 조합 시도
    for root, dirs, files in os.walk(src_dir):
        for f in files:
            full = os.path.join(root, f)
            safe = os.path.relpath(full, src_dir).replace(os.sep, '_').replace('..', '')
            if safe == rel:
                return full
    return None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    sample_n = None
    file_filter = None
    for i, a in enumerate(sys.argv[1:]):
        if a == '--sample' and i + 2 < len(sys.argv):
            sample_n = int(sys.argv[i + 2])
        if a == '--file' and i + 2 < len(sys.argv):
            file_filter = sys.argv[i + 2]

    if not args:
        print("Usage: python3 validate_candidates_runtime.py <language> [--sample N] [--file pattern]")
        sys.exit(1)

    lang = args[0]
    if lang not in LANG_CONFIGS:
        print(f"Unknown language: {lang}")
        sys.exit(1)

    cfg = LANG_CONFIGS[lang]
    db = load_db(cfg['db'])
    debug_dir = os.path.join(cfg['report'], f'debug_coverage_{lang}')

    if not os.path.isdir(debug_dir):
        print(f"Debug dir not found: {debug_dir}")
        sys.exit(1)

    # 검증 대상 수집
    print(f"[*] Language: {lang}")
    print(f"[*] Loading candidates DB...")

    # 각 state에서 고유한 첫 토큰 목록 생성
    state_first_tokens = {}
    for state_str, entries in db.items():
        first_tokens = set()
        for e in entries:
            ft = get_first_token_text(e['key'])
            if ft is not None:
                first_tokens.add((e['key'].split()[0], ft))
        state_first_tokens[state_str] = first_tokens

    # debug CSV에서 커서 위치별 state 목록 읽기
    valid_count = 0
    invalid_count = 0
    skip_count = 0
    total_positions = 0
    invalid_examples = []

    csv_files = sorted(f for f in os.listdir(debug_dir) if f.endswith('.csv'))
    if file_filter:
        csv_files = [f for f in csv_files if file_filter in f]

    print(f"[*] Processing {len(csv_files)} debug CSVs...")

    for ci, csv_name in enumerate(csv_files):
        # 원본 소스 파일 찾기
        src_file = find_source_file(cfg['src'], csv_name)
        if not src_file:
            continue

        with open(src_file, 'rb') as f:
            source_bytes = f.read()

        csv_path = os.path.join(debug_dir, csv_name)
        with open(csv_path, encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # 샘플링
        if sample_n and len(rows) > sample_n:
            import random
            rows = random.sample(rows, sample_n)

        for row in rows:
            try:
                byte_offset = int(row['Location'])
            except (ValueError, KeyError):
                continue

            states_str = row.get('State_List', '')
            try:
                states = ast.literal_eval(states_str)
            except:
                continue

            total_positions += 1

            # 이 위치에서 가능한 모든 첫 토큰 수집
            all_first_tokens = set()
            for s in states:
                s_str = str(s)
                if s_str in state_first_tokens:
                    all_first_tokens.update(state_first_tokens[s_str])

            # 각 첫 토큰에 대해 파싱 검증
            for sym_name, token_text in all_first_tokens:
                has_error, _ = parse_and_check_error(
                    source_bytes, byte_offset, token_text, cfg['grammar_dir']
                )
                if has_error is None:
                    skip_count += 1
                elif has_error:
                    invalid_count += 1
                    if len(invalid_examples) < 20:
                        invalid_examples.append({
                            'file': csv_name,
                            'offset': byte_offset,
                            'token': sym_name,
                            'text': token_text,
                        })
                else:
                    valid_count += 1

        if (ci + 1) % 10 == 0:
            print(f"  [{ci+1}/{len(csv_files)}] valid={valid_count} invalid={invalid_count} skip={skip_count}")

    # 결과 출력
    total = valid_count + invalid_count
    print(f"\n{'='*60}")
    print(f"[결과] 총 커서 위치: {total_positions}")
    print(f"[결과] 검증한 (위치, 토큰) 쌍: {total}")
    print(f"[결과] 유효: {valid_count} ({valid_count/total*100:.1f}%)" if total > 0 else "")
    print(f"[결과] 무효: {invalid_count} ({invalid_count/total*100:.1f}%)" if total > 0 else "")
    print(f"[결과] 스킵: {skip_count}")

    if invalid_examples:
        print(f"\n[무효 사례 (상위 {len(invalid_examples)}개)]")
        for ex in invalid_examples:
            print(f"  {ex['file']}:{ex['offset']}  token={ex['token']} text={ex['text']!r}")


if __name__ == '__main__':
    main()
