#!/usr/bin/env python3
"""
LEARN 데이터 컬렉션 통합 스크립트.
소스 파일을 TreeSitterCutFile.exe로 파싱하여 .data 파일을 생성한다.

사용법: python3 to_data_batch_collect_learn.py <language>
  예: python3 to_data_batch_collect_learn.py c
      python3 to_data_batch_collect_learn.py haskell
"""

import os
import sys
import json
import glob
import subprocess
import shutil
import tempfile

# =================[ 경로 설정 ]=================
ROOT = "/home/hyeonjin/PL"
TS_DIR = os.path.join(ROOT, "tree-sitter")
EXE_PATH = os.path.join(TS_DIR, "TreeSitterCutFile.exe")
CONFIG_PATH = os.path.join(TS_DIR, "lang_config.json")

ARG_ROW = "2147483647"
ARG_COL = "0"
ARG_MODE = "1"  # Collection Mode


def load_config(lang):
    with open(CONFIG_PATH, "r") as f:
        all_config = json.load(f)

    if lang not in all_config:
        print(f"[Error] Unknown language: {lang}")
        print(f"  Supported: {[k for k in all_config if not k.startswith('_')]}")
        sys.exit(1)

    cfg = all_config[lang]
    common = all_config.get("_common", {})

    # ignore_dirs: 공통 + 언어별 추가
    ignore_dirs = set(common.get("ignore_dirs", []))
    ignore_dirs.update(cfg.get("extra_ignore_dirs", []))

    # grammar_subdir로 lib_path 자동 결정
    grammar_subdir = cfg.get("grammar_subdir", "")
    if grammar_subdir:
        grammar_dir = os.path.join(ROOT, f"tree-sitter-{lang}", grammar_subdir)
    else:
        grammar_dir = os.path.join(ROOT, f"tree-sitter-{lang}")

    # .so 파일 자동 탐색
    so_files = glob.glob(os.path.join(grammar_dir, "*.so"))
    if not so_files:
        print(f"[Error] No .so file found in {grammar_dir}")
        sys.exit(1)
    lib_path = so_files[0]

    return {
        "lang": lang,
        "lib_path": lib_path,
        "source_dir": os.path.join(ROOT, "codecompletion_benchmarks", lang, "LEARN"),
        "output_dir": os.path.join(ROOT, "benchmarks_collection", lang, "LEARN_data"),
        "extensions": set(cfg.get("extensions", [])),
        "ignore_dirs": ignore_dirs,
        "exclude_projects": set(cfg.get("exclude_projects", [])),
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 to_data_batch_collect_learn.py <language>")
        sys.exit(1)

    lang = sys.argv[1]
    cfg = load_config(lang)

    source_dir = cfg["source_dir"]
    output_dir = cfg["output_dir"]
    extensions = cfg["extensions"]
    ignore_dirs = cfg["ignore_dirs"]
    exclude_projects = cfg["exclude_projects"]

    if not os.path.isdir(source_dir):
        print(f"[Error] Source directory not found: {source_dir}")
        sys.exit(1)

    if os.path.exists(output_dir):
        try:
            shutil.rmtree(output_dir)
            print(f"[Info] Removed existing directory: {output_dir}")
        except Exception as e:
            print(f"[Error] Failed to remove directory: {e}")
            return

    os.makedirs(output_dir)
    print(f"[Info] Created output directory: {output_dir}")

    work_dir = tempfile.mkdtemp(prefix="collect_")
    print(f"[Info] Work dir: {work_dir}")

    skip_log_path = os.path.join(output_dir, "skipped_files.txt")
    with open(skip_log_path, "w", encoding="utf-8") as f:
        f.write("=== Skipped Files (Parse Error / Recovery Detected) ===\n")

    print(f"[*] Starting recursive scan in: {source_dir}")

    success_count = 0
    skipped_count = 0
    total_found = 0

    for root, dirs, files in os.walk(source_dir):
        # 최상위에서 exclude_projects 적용
        if root == source_dir and exclude_projects:
            dirs[:] = [d for d in dirs if d not in exclude_projects and d not in ignore_dirs]
        else:
            dirs[:] = [d for d in dirs if d not in ignore_dirs]

        for filename in files:
            _, ext = os.path.splitext(filename)
            if ext.lower() not in extensions:
                continue

            total_found += 1

            full_source_path = os.path.join(root, filename)
            rel_path = os.path.relpath(full_source_path, source_dir)

            safe_name = rel_path.replace(os.path.sep, "_").replace("..", "") + ".data"
            final_output_path = os.path.join(output_dir, safe_name)
            generated_file = os.path.join(work_dir, "Test.data")

            if os.path.exists(generated_file):
                os.remove(generated_file)

            print(f"Processing: {rel_path} ...")

            cmd = [EXE_PATH, lang, cfg["lib_path"], full_source_path, ARG_ROW, ARG_COL, ARG_MODE]

            is_skipped = False
            skip_reason = ""

            try:
                result = subprocess.run(
                    cmd, check=False, capture_output=True, text=True, cwd=work_dir
                )

                if "[Skip]" in result.stderr or "[SKIP]" in result.stderr:
                    is_skipped = True
                    skip_reason = "Syntax Error / High Cost"
                    print(f"  -> Detected SKIP signal: {result.stderr.strip()}")
                elif result.returncode != 0:
                    is_skipped = True
                    skip_reason = f"Process Error (Exit Code {result.returncode})"
                    print(f"  -> Process failed: {result.stderr.strip()}")

            except Exception as e:
                is_skipped = True
                skip_reason = str(e)
                print(f"  -> Exception: {e}")

            if not is_skipped and os.path.exists(generated_file) and os.path.getsize(generated_file) > 0:
                if os.path.exists(final_output_path):
                    os.remove(final_output_path)
                shutil.move(generated_file, final_output_path)
                success_count += 1
            else:
                skipped_count += 1
                if os.path.exists(generated_file):
                    os.remove(generated_file)
                if not is_skipped:
                    skip_reason = "No output generated or empty file"
                    print(f"  -> Failed: {skip_reason}")
                with open(skip_log_path, "a", encoding="utf-8") as log_f:
                    log_f.write(f"{rel_path}\n")

    shutil.rmtree(work_dir, ignore_errors=True)

    print("\n" + "=" * 30)
    print(f"[*] SCAN COMPLETED")
    print(f"    - Processed: {success_count}")
    print(f"    - Skipped:   {skipped_count}")
    print(f"    - Total:     {total_found}")
    print(f"    - Saved in:  {output_dir}")
    print(f"    - Log file:  {skip_log_path}")
    print("=" * 30)


if __name__ == "__main__":
    main()
