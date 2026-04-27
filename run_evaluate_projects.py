#!/usr/bin/env python3
"""
run_evaluate_projects.py

특정 언어의 특정 프로젝트(1개 이상)에 대해 구조후보 평가 전체 파이프라인을 실행한다.
  Step 1: Collection (.data 생성)
  Step 2: JSON 생성 (.data → .json)
  Step 3: Evaluation (컨버전 + DB 조회 + 매칭)
  Summary: 프로젝트별 핵심 결과 테이블

사용법:
  python3 run_evaluate_projects.py <lang> <project1> [project2] ...
  python3 run_evaluate_projects.py haskell LPFP learn-haskell-by-example-main
  python3 run_evaluate_projects.py cpp C-Plus-Plus-master cpp-main
"""

import sys
import os
import subprocess
import json
import glob
import shutil
import re
import time
import tempfile
from collections import defaultdict

# =============================================================
# 언어별 설정
# =============================================================
LANG_CONFIGS = {
    "smallbasic": {
        "lang_arg":  "smallbasic",
        "lib":       "/home/hyeonjin/PL/tree-sitter-smallbasic/smallbasic.so",
        "src":       "/home/hyeonjin/PL/codecompletion_benchmarks/smallbasic/TEST",
        "data_dir":  "/home/hyeonjin/PL/benchmarks_collection/smallbasic/TEST_data",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/smallbasic",
        "report_dir":"/home/hyeonjin/PL/tree-sitter/reports/smallbasic",
        "db":        "/home/hyeonjin/PL/code-completion-extension/resources/smallbasic/candidates.json",
        "ext":       ".sb",
        "skip_dirs": {".git"},
    },
    "c": {
        "lang_arg":  "c",
        "lib":       "/home/hyeonjin/PL/tree-sitter-c/c.so",
        "src":       "/home/hyeonjin/PL/codecompletion_benchmarks/c/TEST/ansi_c",
        "data_dir":  "/home/hyeonjin/PL/benchmarks_collection/c/TEST_data",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/c",
        "report_dir":"/home/hyeonjin/PL/tree-sitter/reports/c",
        "db":        "/home/hyeonjin/PL/code-completion-extension/resources/c/candidates.json",
        "ext":       ".c",
        "skip_dirs": {".git"},
    },
    "cpp": {
        "lang_arg":  "cpp",
        "lib":       "/home/hyeonjin/PL/tree-sitter-cpp/cpp.so",
        "src":       "/home/hyeonjin/PL/codecompletion_benchmarks/cpp/TEST",
        "data_dir":  "/home/hyeonjin/PL/benchmarks_collection/cpp/TEST_data",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/cpp",
        "report_dir":"/home/hyeonjin/PL/tree-sitter/reports/cpp",
        "db":        "/home/hyeonjin/PL/code-completion-extension/resources/cpp/candidates.json",
        "ext":       ".cpp",
        "skip_dirs": {".git", "build", "vendor"},
        "exercism":  ("cpp-main", lambda p: p.split("/")[-2] == ".meta" and p.split("/")[-1] in ("example.cpp", "exemplar.cpp")),
    },
    "java": {
        "lang_arg":  "java",
        "lib":       "/home/hyeonjin/PL/tree-sitter-java/java.so",
        "src":       "/home/hyeonjin/PL/codecompletion_benchmarks/java/TEST",
        "data_dir":  "/home/hyeonjin/PL/benchmarks_collection/java/TEST_data",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/java",
        "report_dir":"/home/hyeonjin/PL/tree-sitter/reports/java",
        "db":        "/home/hyeonjin/PL/code-completion-extension/resources/java/candidates.json",
        "ext":       ".java",
        "skip_dirs": {".git", "build", "target"},
        "exercism":  ("java-main", lambda p: "/.meta/src/reference/java/" in p),
    },
    "javascript": {
        "lang_arg":  "javascript",
        "lib":       "/home/hyeonjin/PL/tree-sitter-javascript/javascript.so",
        "src":       "/home/hyeonjin/PL/codecompletion_benchmarks/javascript/TEST",
        "data_dir":  "/home/hyeonjin/PL/benchmarks_collection/javascript/TEST_data",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/javascript",
        "report_dir":"/home/hyeonjin/PL/tree-sitter/reports/javascript",
        "db":        "/home/hyeonjin/PL/code-completion-extension/resources/javascript/candidates.json",
        "ext":       ".js",
        "skip_dirs": {".git", "node_modules", "vendor"},
        "exercism":  ("javascript-main", lambda p: p.split("/")[-2] == ".meta" and p.split("/")[-1] in ("proof.ci.js", "exemplar.js")),
    },
    "python": {
        "lang_arg":  "python",
        "lib":       "/home/hyeonjin/PL/tree-sitter-python/python.so",
        "src":       "/home/hyeonjin/PL/codecompletion_benchmarks/python/TEST",
        "data_dir":  "/home/hyeonjin/PL/benchmarks_collection/python/TEST_data",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/python",
        "report_dir":"/home/hyeonjin/PL/tree-sitter/reports/python",
        "db":        "/home/hyeonjin/PL/code-completion-extension/resources/python/candidates.json",
        "ext":       ".py",
        "skip_dirs": {".git", "build", "__pycache__"},
        "exercism":  ("python-main", lambda p: p.split("/")[-2] == ".meta" and p.split("/")[-1] in ("example.py", "exemplar.py")),
    },
    "php": {
        "lang_arg":  "php",
        "lib":       "/home/hyeonjin/PL/tree-sitter-php/php/parser.so",
        "src":       "/home/hyeonjin/PL/codecompletion_benchmarks/php/TEST",
        "data_dir":  "/home/hyeonjin/PL/benchmarks_collection/php/TEST_data",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/php",
        "report_dir":"/home/hyeonjin/PL/tree-sitter/reports/php",
        "db":        "/home/hyeonjin/PL/code-completion-extension/resources/php/candidates.json",
        "ext":       ".php",
        "skip_dirs": {".git", "vendor", "node_modules"},
        "exercism":  ("php-main", lambda p: p.split("/")[-2] == ".meta" and p.split("/")[-1] in ("example.php", "exemplar.php")),
    },
    "ruby": {
        "lang_arg":  "ruby",
        "lib":       "/home/hyeonjin/PL/tree-sitter-ruby/ruby.so",
        "src":       "/home/hyeonjin/PL/codecompletion_benchmarks/ruby/TEST",
        "data_dir":  "/home/hyeonjin/PL/benchmarks_collection/ruby/TEST_data",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/ruby",
        "report_dir":"/home/hyeonjin/PL/tree-sitter/reports/ruby",
        "db":        "/home/hyeonjin/PL/code-completion-extension/resources/ruby/candidates.json",
        "ext":       ".rb",
        "skip_dirs": {".git", "vendor", "node_modules"},
    },
    "haskell": {
        "lang_arg":  "haskell",
        "lib":       "/home/hyeonjin/PL/tree-sitter-haskell/haskell.so",
        "src":       "/home/hyeonjin/PL/codecompletion_benchmarks/haskell/TEST",
        "data_dir":  "/home/hyeonjin/PL/benchmarks_collection/haskell/TEST_data",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/haskell",
        "report_dir":"/home/hyeonjin/PL/tree-sitter/reports/haskell",
        "db":        "/home/hyeonjin/PL/code-completion-extension/resources/haskell/candidates.json",
        "ext":       ".hs",
        "skip_dirs": {".git", "build", "dist", "dist-newstyle", ".stack-work"},
    },
    "typescript": {
        "lang_arg":  "typescript",
        "lib":       "/home/hyeonjin/PL/tree-sitter-typescript/typescript/parser.so",
        "src":       "/home/hyeonjin/PL/codecompletion_benchmarks/typescript/TEST",
        "data_dir":  "/home/hyeonjin/PL/benchmarks_collection/typescript/TEST_data",
        "json_dir":  "/home/hyeonjin/PL/tree-sitter/reports/typescript",
        "report_dir":"/home/hyeonjin/PL/tree-sitter/reports/typescript",
        "db":        "/home/hyeonjin/PL/code-completion-extension/resources/typescript/candidates.json",
        "ext":       ".ts",
        "skip_dirs": {".git", "node_modules", "dist", "build"},
        "exercism":  ("exercism-typescript-main", lambda p: p.split("/")[-2] == ".meta" and p.split("/")[-1] in ("proof.ci.ts", "exemplar.ts")),
    },
}

TS_DIR = os.path.dirname(os.path.abspath(__file__))
EXE_PATH = os.path.join(TS_DIR, "TreeSitterCutFile.exe")
MAX_CANDIDATE_LIST_SIZE = 20


# =============================================================
# Step 1: Collection (.data 생성)
# =============================================================
def step_collect(cfg, project, work_dir):
    """프로젝트의 소스 파일들을 컬렉션하여 .data 생성"""
    scan_root = os.path.join(cfg["src"], project)
    if not os.path.isdir(scan_root):
        print(f"  [Error] Not found: {scan_root}")
        return 0

    data_dir = cfg["data_dir"]
    os.makedirs(data_dir, exist_ok=True)

    # 기존 해당 프로젝트 .data 삭제
    prefix = project + "_"
    for f in os.listdir(data_dir):
        if f.startswith(prefix) and f.endswith(".data"):
            os.remove(os.path.join(data_dir, f))

    ext = cfg["ext"]
    skip_dirs = cfg.get("skip_dirs", set())
    exercism = cfg.get("exercism")
    success = skip = total = 0

    for root, dirs, files in os.walk(scan_root):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for filename in files:
            if not filename.endswith(ext):
                continue
            full_path = os.path.join(root, filename)
            # exercism 필터
            if exercism and project == exercism[0]:
                rel = os.path.relpath(full_path, cfg["src"])
                if not exercism[1](rel):
                    continue
            total += 1
            rel_path = os.path.relpath(full_path, cfg["src"])
            safe_name = rel_path.replace(os.sep, "_") + ".data"
            out_path = os.path.join(data_dir, safe_name)

            gen_file = os.path.join(work_dir, "Test.data")
            if os.path.exists(gen_file):
                os.remove(gen_file)

            cmd = [EXE_PATH, cfg["lang_arg"], cfg["lib"], full_path, "1"]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True,
                                       encoding="utf-8", errors="replace", cwd=work_dir)
                is_skip = "[Skip]" in result.stderr or result.returncode != 0
            except Exception:
                is_skip = True

            if not is_skip and os.path.exists(gen_file) and os.path.getsize(gen_file) > 0:
                shutil.move(gen_file, out_path)
                success += 1
            else:
                skip += 1
                if os.path.exists(gen_file):
                    os.remove(gen_file)

    print(f"  Collection: {success} ok, {skip} skip, {total} total")
    return success


# =============================================================
# Step 2: JSON 생성 (.data → .json)
# =============================================================
def parse_data_file(path):
    """공통 .data → dict 파싱"""
    data = {}
    state = None
    candidate = ""
    waiting = False
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip()
            if not line:
                continue
            if not line[0].isspace():
                parts = line.split(maxsplit=1)
                if parts and parts[0].isdigit():
                    state = int(parts[0])
                    candidate = parts[1] if len(parts) > 1 else ""
                    waiting = True
            elif waiting and line.strip():
                if ":" in line:
                    loc = line.split(":", 1)[0].strip().lstrip("@")
                    if loc not in data:
                        data[loc] = []
                    data[loc].append({"state_id": state, "candidate": candidate})
                    waiting = False
    return data


def step_json(cfg, project):
    """프로젝트의 .data → .json 변환"""
    data_dir = cfg["data_dir"]
    json_dir = cfg["json_dir"]
    os.makedirs(json_dir, exist_ok=True)

    prefix = project + "_"
    # 기존 해당 프로젝트 .json 삭제
    for f in os.listdir(json_dir):
        if f.startswith(prefix) and f.endswith(".json"):
            os.remove(os.path.join(json_dir, f))

    data_files = [f for f in glob.glob(os.path.join(data_dir, "*.data"))
                  if os.path.basename(f).startswith(prefix)]

    count = 0
    for df in data_files:
        try:
            result = parse_data_file(df)
            jf = os.path.join(json_dir, os.path.basename(df).replace(".data", ".json"))
            with open(jf, "w", encoding="utf-8") as out:
                json.dump(result, out, indent=2, ensure_ascii=False)
            count += 1
        except Exception as e:
            print(f"  [Error] {os.path.basename(df)}: {e}")

    print(f"  JSON: {count}/{len(data_files)} converted")
    return count


# =============================================================
# Step 3: Evaluation
# =============================================================
def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run_at_position(lang_arg, lib, target_file, byte_offset, work_dir):
    cmd = [EXE_PATH, lang_arg, lib, target_file, str(byte_offset), "2"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", cwd=work_dir)
        if result.returncode != 0:
            return []
        for line in result.stdout.splitlines():
            m = re.search(r"@@PREDICT:\s*([\d\s]+)", line)
            if m:
                raw = m.group(1).strip()
                if not raw:
                    return []
                return [int(s) for s in raw.split() if s.isdigit()]
        return []
    except Exception:
        return []


def collect_source_files(cfg, project):
    """프로젝트의 소스 파일 목록과 safe_name 매핑을 반환"""
    scan_root = os.path.join(cfg["src"], project)
    ext = cfg["ext"]
    skip_dirs = cfg.get("skip_dirs", set())
    exercism = cfg.get("exercism")
    files = []  # [(full_path, safe_name), ...]

    for root, dirs, fnames in os.walk(scan_root):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for filename in fnames:
            if not filename.endswith(ext):
                continue
            full_path = os.path.join(root, filename)
            if exercism and project == exercism[0]:
                rel = os.path.relpath(full_path, cfg["src"])
                if not exercism[1](rel):
                    continue
            rel_path = os.path.relpath(full_path, cfg["src"])
            safe_name = rel_path.replace(os.sep, "_")
            files.append((full_path, safe_name))
    return sorted(files)


def step_evaluate(cfg, project, db, work_dir):
    """프로젝트의 소스 파일을 순회하며 평가 (소스→JSON 방향)"""
    json_dir = cfg["json_dir"]
    report_dir = cfg["report_dir"]
    lang_arg = cfg["lang_arg"]
    lib = cfg["lib"]

    source_files = collect_source_files(cfg, project)

    # 통계
    total = found = not_found = fail = 0
    top1 = top3 = top5 = top10 = top20 = 0

    debug_dir = os.path.join(report_dir, f"debug_coverage_{lang_arg}")
    os.makedirs(debug_dir, exist_ok=True)

    for full_path, safe_name in source_files:
        json_path = os.path.join(json_dir, safe_name + ".json")
        if not os.path.exists(json_path):
            continue

        answers = load_json(json_path)
        if not answers:
            continue

        debug_logs = []

        for loc_key, gt_data in answers.items():
            try:
                byte_offset = int(loc_key)
            except ValueError:
                continue
            if not gt_data:
                continue

            states = run_at_position(lang_arg, lib, full_path, byte_offset, work_dir)

            if not states:
                debug_logs.append([loc_key, gt_data[0]["candidate"], "FAIL", "FAIL", 0])
                fail += 1
                total += 1
                continue

            # Found 판정
            merged = defaultdict(int)
            for s in states:
                sk = str(s)
                if sk in db:
                    for item in db[sk]:
                        merged[item["key"]] += item["value"]

            gt_clean_set = {e["candidate"].replace(" ", "") for e in gt_data}
            is_found = any(k.replace(" ", "") in gt_clean_set for k in merged)

            if is_found:
                found += 1
                label = "FOUND"
            else:
                not_found += 1
                label = "NOT_FOUND"

            # 랭크
            ranked = sorted(merged.items(), key=lambda x: x[1], reverse=True)[:MAX_CANDIDATE_LIST_SIZE]
            best_rank = 0
            best_entry = gt_data[0]
            for e in gt_data:
                ec = e["candidate"].replace(" ", "")
                for r, (k, _) in enumerate(ranked, 1):
                    if k.replace(" ", "") == ec:
                        if best_rank == 0 or r < best_rank:
                            best_rank = r
                            best_entry = e
                        break

            if best_rank > 0:
                if best_rank == 1: top1 += 1
                if best_rank <= 3: top3 += 1
                if best_rank <= 5: top5 += 1
                if best_rank <= 10: top10 += 1
                if best_rank <= 20: top20 += 1

            debug_logs.append([loc_key, best_entry["candidate"],
                              str(states), label, best_rank])
            total += 1

        # debug CSV 저장
        import csv
        csv_path = os.path.join(debug_dir, f"{safe_name}.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Location", "Ground_Truth", "State_List", "Coverage_Result", "Rank"])
            w.writerows(debug_logs)

    return {
        "project": project,
        "total": total,
        "found": found,
        "not_found": not_found,
        "fail": fail,
        "top1": top1, "top3": top3, "top5": top5,
        "top10": top10, "top20": top20,
    }


    # (find_source_file 삭제: safe_name→경로 역변환은 모호하므로
    #  소스 파일에서 JSON을 찾는 방식(collect_source_files)으로 대체)


# =============================================================
# Summary 출력
# =============================================================
def print_summary(results):
    def pct(n, t):
        return f"{n/t*100:.1f}%" if t > 0 else "  -  "

    print()
    print("=" * 80)
    print(f"  {'Project':<35s} {'Total':>6s}  {'Top-10':>8s}  {'Found':>8s}  {'NotFound':>8s}  {'Fail':>6s}")
    print("-" * 80)
    g_total = g_found = g_nf = g_fail = g_top10 = 0
    for r in results:
        t = r["total"]
        print(f"  {r['project']:<35s} {t:>6d}  {pct(r['top10'],t):>8s}  {pct(r['found'],t):>8s}  {pct(r['not_found'],t):>8s}  {r['fail']:>6d}")
        g_total += t; g_found += r["found"]; g_nf += r["not_found"]
        g_fail += r["fail"]; g_top10 += r["top10"]
    if len(results) > 1:
        print("-" * 80)
        print(f"  {'TOTAL':<35s} {g_total:>6d}  {pct(g_top10,g_total):>8s}  {pct(g_found,g_total):>8s}  {pct(g_nf,g_total):>8s}  {g_fail:>6d}")
    print("=" * 80)


# =============================================================
# Main
# =============================================================
def main():
    if len(sys.argv) < 3:
        print("Usage: python3 run_evaluate_projects.py <lang> <project1> [project2] ...")
        print(f"  Languages: {', '.join(sorted(LANG_CONFIGS.keys()))}")
        return

    lang = sys.argv[1]
    projects = sys.argv[2:]

    if lang not in LANG_CONFIGS:
        print(f"[Error] Unknown language: {lang}")
        print(f"  Available: {', '.join(sorted(LANG_CONFIGS.keys()))}")
        return

    cfg = LANG_CONFIGS[lang]

    # 프로젝트 존재 확인
    for p in projects:
        proj_dir = os.path.join(cfg["src"], p)
        if not os.path.isdir(proj_dir):
            print(f"[Error] Project not found: {proj_dir}")
            available = [d for d in os.listdir(cfg["src"])
                        if os.path.isdir(os.path.join(cfg["src"], d))]
            print(f"  Available: {', '.join(sorted(available))}")
            return

    # DB 로드
    print(f"[*] Loading DB: {cfg['db']}")
    db = load_json(cfg["db"])
    print(f"    {len(db)} states loaded")

    # 임시 작업 디렉토리 생성 (동시 실행 시 충돌 방지)
    work_dir = tempfile.mkdtemp(prefix=f"eval_{lang}_")
    print(f"[*] Work dir: {work_dir}")

    start = time.time()
    results = []

    try:
        for project in projects:
            print(f"\n{'='*60}")
            print(f"  [{lang}] Project: {project}")
            print(f"{'='*60}")

            print(f"  [Step 1/3] Collection...")
            step_collect(cfg, project, work_dir)

            print(f"  [Step 2/3] JSON generation...")
            step_json(cfg, project)

            print(f"  [Step 3/3] Evaluation...")
            r = step_evaluate(cfg, project, db, work_dir)
            results.append(r)

            t = r["total"]
            if t > 0:
                print(f"  Result: {t} queries, Top-10={r['top10']}/{t} ({r['top10']/t*100:.1f}%), Found={r['found']}/{t} ({r['found']/t*100:.1f}%)")
    finally:
        # 임시 디렉토리 정리
        shutil.rmtree(work_dir, ignore_errors=True)

    elapsed = time.time() - start
    print(f"\n[*] Total elapsed: {elapsed:.1f}s")

    print_summary(results)


if __name__ == "__main__":
    main()
