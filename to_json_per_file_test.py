#!/usr/bin/env python3
"""
TEST 컬렉션 정답지 구성 통합 스크립트.
.data 파일을 개별 .json 파일로 변환한다.

사용법:
  python3 to_json_per_file_test.py <language>              # 전체 변환
  python3 to_json_per_file_test.py <language> <project>    # 특정 프로젝트만

JSON 포맷:
{
  "<first_byte>": [
    {
      "state_id": <int>,
      "candidate": "<structural candidate>",
      "candidate_text": "<original source slice covered by this candidate>"
    },
    ...
  ]
}

NOTE — candidate_text 는 디버깅/표시용 필드.
  - 평가 파이프라인(evaluate_coverage.py)은 키(byte offset)와 candidate(symbol 시퀀스)만 사용한다.
  - 컬렉션 라이터(lib/src/parser.c:dump_lexemes)가 multi-line 비단말 노드의 source 텍스트를 escape 없이
    덤프하기 때문에, 그 노드를 포함하는 entry 의 candidate_text 는 첫 줄까지만 잡혀 잘릴 수 있다.
  - 즉 candidate_text 가 잘린 형태로 보이더라도 평가 결과에는 영향 없음. 사람이 JSON 을 직접 읽거나
    별도 분석 스크립트가 텍스트 전체를 필요로 할 때만 신뢰성에 주의.
"""

import sys
import os
import glob
import json
import shutil

# =================[ 경로 설정 ]=================
ROOT = "/home/hyeonjin/PL"
TS_DIR = os.path.join(ROOT, "tree-sitter")
CONFIG_PATH = os.path.join(TS_DIR, "lang_config.json")


def load_lang_config(lang: str) -> dict:
    with open(CONFIG_PATH, "r") as f:
        cfg = json.load(f)
    if lang not in cfg:
        print(f"[Error] Unknown language: {lang}")
        sys.exit(1)
    common = cfg.get("_common", {})
    langcfg = cfg[lang]
    ignore_dirs = set(common.get("ignore_dirs", []))
    ignore_dirs.update(langcfg.get("extra_ignore_dirs", []))
    exts = langcfg.get("extensions", [])
    if isinstance(exts, str):
        exts = [exts]
    return {
        "extensions": tuple(exts),
        "ignore_dirs": ignore_dirs,
    }


def build_source_map(test_dir: str, extensions: tuple, ignore_dirs: set) -> dict:
    """
    TEST 디렉토리를 walk 하여 data-safe-name → source 파일 full path 매핑 구축.
    safe_name 은 to_data_batch_collect_test.py 와 동일한 규칙:
        rel_path.replace(os.path.sep, "_").replace("..", "")
    """
    mapping = {}
    for root, dirs, files in os.walk(test_dir):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        for fn in files:
            _, ext = os.path.splitext(fn)
            if ext.lower() not in extensions:
                continue
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, test_dir)
            safe = rel.replace(os.path.sep, "_").replace("..", "")
            mapping[safe] = full
    return mapping


def _flush_block(extracted, state, candidate, block, source_bytes):
    if not block or state is None:
        return
    first_loc, _ = block[0]
    last_loc, last_len = block[-1]
    end_byte = last_loc + last_len
    if end_byte > len(source_bytes):
        end_byte = len(source_bytes)
    text = source_bytes[first_loc:end_byte].decode("utf-8", errors="replace")
    key = str(first_loc)
    extracted.setdefault(key, []).append({
        "state_id": state,
        "candidate": candidate,
        "candidate_text": text,
    })


def process_one_data_file(data_path: str, source_path: str) -> dict:
    """
    .data 파일 + 원본 소스 → JSON dict
    """
    with open(source_path, "rb") as f:
        source_bytes = f.read()

    extracted = {}
    current_state = None
    current_candidate = ""
    current_block = []  # list of (loc:int, lex_byte_len:int)

    with open(data_path, "r", encoding="utf-8", errors="replace") as f:
        for raw_line in f:
            # EOL 제거하되 lexeme 내부 공백은 보존
            line = raw_line.rstrip("\n")

            if not line.strip():
                # 블록 종료
                _flush_block(extracted, current_state, current_candidate,
                             current_block, source_bytes)
                current_block = []
                current_state = None
                current_candidate = ""
                continue

            if not line[0].isspace():
                # 새 State+Candidate 라인
                _flush_block(extracted, current_state, current_candidate,
                             current_block, source_bytes)
                current_block = []
                parts = line.split(maxsplit=1)
                if parts and parts[0].isdigit():
                    current_state = int(parts[0])
                    current_candidate = parts[1] if len(parts) > 1 else ""
                else:
                    current_state = None
                    current_candidate = ""
            else:
                # @<loc>: <lexeme> 라인
                s = line.lstrip()
                if not s.startswith("@"):
                    continue
                body = s[1:]
                colon_idx = body.find(":")
                if colon_idx < 0:
                    continue
                loc_str = body[:colon_idx].strip()
                lex = body[colon_idx + 1:]
                # dump_lexemes 출력은 ": " 형태(콜론+공백1칸)이므로 공백 1칸 제거
                if lex.startswith(" "):
                    lex = lex[1:]
                try:
                    loc = int(loc_str)
                except ValueError:
                    continue
                lex_bytes = len(lex.encode("utf-8"))
                current_block.append((loc, lex_bytes))

    # 파일 끝에서 마지막 블록 flush
    _flush_block(extracted, current_state, current_candidate,
                 current_block, source_bytes)

    return extracted


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 to_json_per_file_test.py <language> [project]")
        sys.exit(1)

    lang = sys.argv[1]
    project = sys.argv[2] if len(sys.argv) > 2 else None

    langcfg = load_lang_config(lang)
    input_dir = os.path.join(ROOT, "benchmarks_collection", lang, "TEST_data")
    test_src_dir = os.path.join(ROOT, "codecompletion_benchmarks", lang, "TEST")
    output_dir = os.path.join(TS_DIR, "reports", lang)

    if not os.path.isdir(input_dir):
        print(f"[Error] Input directory not found: {input_dir}")
        sys.exit(1)
    if not os.path.isdir(test_src_dir):
        print(f"[Error] TEST source directory not found: {test_src_dir}")
        sys.exit(1)

    source_map = build_source_map(test_src_dir, langcfg["extensions"], langcfg["ignore_dirs"])
    print(f"[Info] Built source map: {len(source_map)} files")

    if project:
        os.makedirs(output_dir, exist_ok=True)
        prefix = project.replace(os.path.sep, "_") + "_"
        for f in os.listdir(output_dir):
            if f.startswith(prefix) and f.endswith(".json"):
                os.remove(os.path.join(output_dir, f))
                print(f"[Info] Removed old: {f}")
        data_files = [
            f for f in glob.glob(os.path.join(input_dir, "*.data"))
            if os.path.basename(f).startswith(prefix)
        ]
        print(f"[*] Project mode: {project} ({len(data_files)} .data files)")
    else:
        if os.path.exists(output_dir):
            try:
                shutil.rmtree(output_dir)
                print(f"[Info] Removed existing directory: {output_dir}")
            except Exception as e:
                print(f"[Error] Failed to remove directory: {e}")
                return
        os.makedirs(output_dir)
        print(f"[Info] Created output directory: {output_dir}")
        data_files = glob.glob(os.path.join(input_dir, "*.data"))

    print(f"[*] Found {len(data_files)} files.")
    success_count = 0
    missing_source = 0
    for data_file in data_files:
        filename = os.path.basename(data_file)
        # ".data" 제거 후 safe_name 으로 source 조회
        safe_name = filename[:-5] if filename.endswith(".data") else filename
        source_path = source_map.get(safe_name)
        if source_path is None:
            print(f"[Warn] Source not found for: {filename} (safe={safe_name})")
            missing_source += 1
            continue

        json_filename = filename.replace(".data", ".json")
        output_path = os.path.join(output_dir, json_filename)

        try:
            result_dict = process_one_data_file(data_file, source_path)
            with open(output_path, "w", encoding="utf-8") as out:
                json.dump(result_dict, out, indent=2, ensure_ascii=False)
            print(f" -> Converted: {json_filename} ({len(result_dict)} keys)")
            success_count += 1
        except Exception as e:
            print(f"[Error] Failed to convert {filename}: {e}")

    print(f"[*] All done. Processed {success_count}/{len(data_files)} files.")
    if missing_source:
        print(f"[Warn] {missing_source} .data files had no matching source.")


if __name__ == "__main__":
    main()
