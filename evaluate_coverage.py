import sys
import os
import json
import subprocess
import time
import csv
import re
from collections import defaultdict

# =================[ 언어별 설정 ]=================

LANG_CONFIGS = {
    "smallbasic": {
        "lib":       "/home/hyeonjin/PL/tree-sitter-smallbasic/smallbasic.so",
        "src":       "/home/hyeonjin/PL/codecompletion_benchmarks/smallbasic/TEST_BENCH",
        "answer":    "/home/hyeonjin/PL/tree-sitter/reports/smallbasic",
        "report":    "/home/hyeonjin/PL/tree-sitter/reports/smallbasic",
        "db":        "/home/hyeonjin/PL/code-completion-extension/resources/smallbasic/candidates.json",
        "ext":       ".sb",
        "walk":      False,  # glob (flat)
        "exercism":  None,
        "strip_ext": True,   # JSON명: foo.sb -> foo.json (확장자 제거 후 .json)
    },
    "c": {
        "lib":       "/home/hyeonjin/PL/tree-sitter-c/c.so",
        "src":       "/home/hyeonjin/PL/codecompletion_benchmarks/c11/TEST_BENCH/ansi_c",
        "answer":    "/home/hyeonjin/PL/tree-sitter/reports/c11",
        "report":    "/home/hyeonjin/PL/tree-sitter/reports/c11",
        "db":        "/home/hyeonjin/PL/code-completion-extension/resources/c/candidates.json",
        "ext":       ".c",
        "walk":      True,
        "exercism":  None,
    },
    "cpp": {
        "lib":       "/home/hyeonjin/PL/tree-sitter-cpp/cpp.so",
        "src":       "/home/hyeonjin/PL/codecompletion_benchmarks/cpp/TEST",
        "answer":    "/home/hyeonjin/PL/tree-sitter/reports/cpp",
        "report":    "/home/hyeonjin/PL/tree-sitter/reports/cpp",
        "db":        "/home/hyeonjin/PL/code-completion-extension/resources/cpp/candidates.json",
        "ext":       ".cpp",
        "walk":      True,
        "exercism":  ("cpp-main", lambda p: p.split("/")[-2] == ".meta" and p.split("/")[-1] in ("example.cpp", "exemplar.cpp")),
        "skip_dirs": {".git", "build", "vendor"},
    },
    "java": {
        "lib":       "/home/hyeonjin/PL/tree-sitter-java/java.so",
        "src":       "/home/hyeonjin/PL/codecompletion_benchmarks/java/TEST",
        "answer":    "/home/hyeonjin/PL/tree-sitter/reports/java",
        "report":    "/home/hyeonjin/PL/tree-sitter/reports/java",
        "db":        "/home/hyeonjin/PL/code-completion-extension/resources/java/candidates.json",
        "ext":       ".java",
        "walk":      True,
        "exercism":  ("java-main", lambda p: "/.meta/src/reference/java/" in p),
        "skip_dirs": {".git", "build", "target"},
    },
    "javascript": {
        "lib":       "/home/hyeonjin/PL/tree-sitter-javascript/javascript.so",
        "src":       "/home/hyeonjin/PL/codecompletion_benchmarks/javascript/TEST",
        "answer":    "/home/hyeonjin/PL/tree-sitter/reports/javascript",
        "report":    "/home/hyeonjin/PL/tree-sitter/reports/javascript",
        "db":        "/home/hyeonjin/PL/code-completion-extension/resources/javascript/candidates.json",
        "ext":       ".js",
        "walk":      True,
        "exercism":  ("javascript-main", lambda p: p.split("/")[-2] == ".meta" and p.split("/")[-1] in ("proof.ci.js", "exemplar.js")),
        "skip_dirs": {".git", "node_modules", "vendor"},
    },
    "python": {
        "lib":       "/home/hyeonjin/PL/tree-sitter-python/python.so",
        "src":       "/home/hyeonjin/PL/codecompletion_benchmarks/python/TEST",
        "answer":    "/home/hyeonjin/PL/tree-sitter/reports/python",
        "report":    "/home/hyeonjin/PL/tree-sitter/reports/python",
        "db":        "/home/hyeonjin/PL/code-completion-extension/resources/python/candidates.json",
        "ext":       ".py",
        "walk":      True,
        "exercism":  ("python-main", lambda p: p.split("/")[-2] == ".meta" and p.split("/")[-1] in ("example.py", "exemplar.py")),
        "skip_dirs": {".git", "build", "__pycache__"},
    },
    "php": {
        "lib":       "/home/hyeonjin/PL/tree-sitter-php/php/parser.so",
        "src":       "/home/hyeonjin/PL/codecompletion_benchmarks/php/TEST",
        "answer":    "/home/hyeonjin/PL/tree-sitter/reports/php",
        "report":    "/home/hyeonjin/PL/tree-sitter/reports/php",
        "db":        "/home/hyeonjin/PL/code-completion-extension/resources/php/candidates.json",
        "ext":       ".php",
        "walk":      True,
        "exercism":  ("php-main", lambda p: p.split("/")[-2] == ".meta" and p.split("/")[-1] in ("example.php", "exemplar.php")),
        "skip_dirs": {".git", "vendor", "node_modules"},
    },
    "ruby": {
        "lib":       "/home/hyeonjin/PL/tree-sitter-ruby/ruby.so",
        "src":       "/home/hyeonjin/PL/codecompletion_benchmarks/ruby/TEST",
        "answer":    "/home/hyeonjin/PL/tree-sitter/reports/ruby",
        "report":    "/home/hyeonjin/PL/tree-sitter/reports/ruby",
        "db":        "/home/hyeonjin/PL/code-completion-extension/resources/ruby/candidates.json",
        "ext":       ".rb",
        "walk":      True,
        "exercism":  None,
        "skip_dirs": {".git", "vendor", "node_modules"},
    },
    "haskell": {
        "lib":       "/home/hyeonjin/PL/tree-sitter-haskell/haskell.so",
        "src":       "/home/hyeonjin/PL/codecompletion_benchmarks/haskell/TEST",
        "answer":    "/home/hyeonjin/PL/tree-sitter/reports/haskell",
        "report":    "/home/hyeonjin/PL/tree-sitter/reports/haskell",
        "db":        "/home/hyeonjin/PL/code-completion-extension/resources/haskell/candidates.json",
        "ext":       ".hs",
        "walk":      True,
        "exercism":  None,
        "skip_dirs": {".git", "build", "dist", "dist-newstyle", ".stack-work"},
    },
}

EXE_PATH = "/home/hyeonjin/PL/tree-sitter/TreeSitterCutFile.exe"
MAX_CANDIDATE_LIST_SIZE = 20

# =========================================================

class EvaluationReporter:
    def __init__(self, lang: str, cfg: dict):
        self.lang = lang
        self.cfg  = cfg
        self.db   = self._load_json(cfg["db"])

        # 커버리지 통계
        self.total_queries   = 0
        self.found_count     = 0
        self.not_found_count = 0
        self.fail_count      = 0

        # 랭크 통계
        self.rank_stats          = defaultdict(int)

        self.file_reports = []

        os.makedirs(cfg["report"], exist_ok=True)

    def _load_json(self, path):
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _run_at_position(self, target_file, row, col):
        cmd = [EXE_PATH, self.lang, self.cfg["lib"], target_file, str(row), str(col), "0"]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace"
            )
            if result.returncode != 0:
                return []
            for line in result.stdout.splitlines():
                match = re.search(r"@@PREDICT:\s*([\d\s]+)", line)
                if match:
                    raw = match.group(1).strip()
                    if not raw:
                        return []
                    states = []
                    for s in raw.split():
                        try:
                            states.append(int(s))
                        except ValueError:
                            pass
                    return states
            return []
        except Exception:
            return []

    def _lookup_db_ranked(self, states):
        """Top-N 랭크 계산용: 점수 내림차순 정렬된 (key, score) 리스트 반환."""
        merged = defaultdict(int)
        for state in states:
            s_key = str(state)
            if s_key in self.db:
                for item in self.db[s_key]:
                    merged[item["key"]] += item["value"]
        return sorted(merged.items(), key=lambda x: x[1], reverse=True)

    def _lookup_db_full(self, states):
        """커버리지용: 크기 제한 없이 DB에서 모든 후보 조회."""
        merged = defaultdict(int)
        for state in states:
            s_key = str(state)
            if s_key in self.db:
                for item in self.db[s_key]:
                    merged[item["key"]] += item["value"]
        return merged

    def _get_rank(self, candidates, ground_truth):
        gt_clean = ground_truth.replace(" ", "")
        for rank, (key, _) in enumerate(candidates, 1):
            if key.replace(" ", "") == gt_clean:
                return rank
        return 0

    def _is_found(self, candidates_map: dict, ground_truth: str) -> bool:
        gt_clean = ground_truth.replace(" ", "")
        for key in candidates_map:
            if key.replace(" ", "") == gt_clean:
                return True
        return False

    def _collect_files(self):
        cfg = self.cfg
        src = cfg["src"]
        ext = cfg["ext"]
        exercism = cfg.get("exercism")
        skip_dirs = cfg.get("skip_dirs", set())

        if not cfg["walk"]:
            import glob as _glob
            return sorted(_glob.glob(os.path.join(src, f"*{ext}")))

        target_files = []
        for root, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for filename in files:
                if not filename.endswith(ext):
                    continue
                full_path = os.path.join(root, filename)
                if exercism:
                    proj_name, filter_fn = exercism
                    rel_unix = os.path.relpath(full_path, src).replace(os.path.sep, "/")
                    top = rel_unix.split("/")[0]
                    if top == proj_name and not filter_fn(rel_unix):
                        continue
                target_files.append(full_path)
        return target_files

    def _safe_name(self, target_file):
        try:
            rel = os.path.relpath(target_file, self.cfg["src"])
        except ValueError:
            rel = os.path.basename(target_file)
        return rel.replace(os.path.sep, "_").replace("..", "")

    def evaluate_file(self, target_file):
        safe_name = self._safe_name(target_file)
        if self.cfg.get("strip_ext"):
            base, _ = os.path.splitext(safe_name)
            json_path = os.path.join(self.cfg["answer"], base + ".json")
        else:
            json_path = os.path.join(self.cfg["answer"], safe_name + ".json")

        if not os.path.exists(json_path):
            return

        answers = self._load_json(json_path)
        if not answers:
            return

        f_total     = 0
        f_found     = 0
        f_not_found = 0
        f_fail      = 0
        f_top1      = 0
        f_top3      = 0
        f_top5      = 0
        f_top10     = 0
        f_top20     = 0
        debug_logs  = []

        total_locs = len(answers)
        processed  = 0
        print(f" -> {safe_name} ({total_locs} points)...")

        for loc_key, gt_data in answers.items():
            processed += 1
            if processed % 10 == 0:
                print(f"    {processed}/{total_locs}...", end="\r")

            nums = re.findall(r"\d+", loc_key)
            if len(nums) < 2:
                continue
            row, col = int(nums[0]), int(nums[1])

            # gt_data는 [{"state_id": int, "candidate": str}, ...] 리스트
            if not gt_data:
                continue

            states = self._run_at_position(target_file, row, col)

            if not states:
                result_label = "FAIL"
                rank = 0
                f_fail += 1
                ground_truth = gt_data[0]["candidate"]
            else:
                # FOUND: gt_data의 후보 중 하나라도 DB에 있으면
                candidates_full = self._lookup_db_full(states)
                if any(self._is_found(candidates_full, e["candidate"]) for e in gt_data):
                    result_label = "FOUND"
                    f_found += 1
                else:
                    result_label = "NOT_FOUND"
                    f_not_found += 1

                # 랭크: gt_data 후보들 중 가장 좋은(낮은) 순위
                top_candidates = self._lookup_db_ranked(states)[:MAX_CANDIDATE_LIST_SIZE]
                best_rank = 0
                best_entry = gt_data[0]
                for e in gt_data:
                    r = self._get_rank(top_candidates, e["candidate"])
                    if r > 0 and (best_rank == 0 or r < best_rank):
                        best_rank = r
                        best_entry = e
                rank = best_rank
                ground_truth = best_entry["candidate"]

                if rank > 0:
                    self.rank_stats[rank] += 1
                    if rank == 1:       f_top1  += 1
                    if rank <= 3:       f_top3  += 1
                    if rank <= 5:       f_top5  += 1
                    if rank <= 10:      f_top10 += 1
                    if rank <= 20:      f_top20 += 1

            debug_logs.append([loc_key, ground_truth, str(states) if states else "FAIL", result_label, rank])
            f_total += 1
            self.total_queries += 1

        print(f"    Done. ({f_total} queries)")

        self.found_count     += f_found
        self.not_found_count += f_not_found
        self.fail_count      += f_fail

        self.file_reports.append({
            "name":      safe_name,
            "total":     f_total,
            "found":     f_found,
            "not_found": f_not_found,
            "fail":      f_fail,
            "top1":      f_top1,
            "top3":      f_top3,
            "top5":      f_top5,
            "top10":     f_top10,
            "top20":     f_top20,
        })

        self._save_debug_log(safe_name, debug_logs)

    def _save_debug_log(self, safe_name, log_data):
        debug_dir = os.path.join(self.cfg["report"], f"debug_coverage_{self.lang}")
        os.makedirs(debug_dir, exist_ok=True)
        csv_path = os.path.join(debug_dir, f"{safe_name}.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Location", "Ground_Truth", "State_List", "Coverage_Result", "Rank"])
            writer.writerows(log_data)

    def save_report(self, suffix=""):
        report_dir = self.cfg["report"]

        # 파일별 성능 리포트 (랭크 + 커버리지 통합)
        perf_path = os.path.join(report_dir, f"{self.lang}_file_performance{suffix}.csv")
        with open(perf_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "File Name", "Total",
                "Top-1 Acc (%)", "Top-3 Acc (%)", "Top-5 Acc (%)", "Top-10 Acc (%)", "Top-20 Acc (%)",
                "Found", "Found (%)", "Not Found", "Not Found (%)", "Fail", "Fail (%)"
            ])
            for r in self.file_reports:
                total = r["total"]
                def pct(n): return round(n / total * 100, 2) if total > 0 else 0.0
                writer.writerow([
                    r["name"], total,
                    pct(r["top1"]), pct(r["top3"]), pct(r["top5"]), pct(r["top10"]), pct(r["top20"]),
                    r["found"],     pct(r["found"]),
                    r["not_found"], pct(r["not_found"]),
                    r["fail"],      pct(r["fail"]),
                ])
        print(f"[Saved] File Report (CSV) -> {perf_path}")

        # 커버리지 전용 리포트 (기존 형식 유지)
        cov_path = os.path.join(report_dir, f"{self.lang}_coverage{suffix}.csv")
        with open(cov_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "File Name", "Total",
                "Found", "Found (%)",
                "Not Found", "Not Found (%)",
                "Fail", "Fail (%)"
            ])
            for r in self.file_reports:
                total = r["total"]
                def pct(n): return round(n / total * 100, 2) if total > 0 else 0.0
                writer.writerow([
                    r["name"], total,
                    r["found"],     pct(r["found"]),
                    r["not_found"], pct(r["not_found"]),
                    r["fail"],      pct(r["fail"]),
                ])
        print(f"[Saved] Coverage Report (CSV) -> {cov_path}")

    def aggregate_per_project(self):
        """이미 생성된 debug CSV를 프로젝트별로 집계하여 evaluate_struct_<lang>.py <project> 와
        동일한 출력 형식으로 출력하고, 프로젝트별 CSV 리포트를 저장한다."""
        debug_dir = os.path.join(self.cfg["report"], f"debug_coverage_{self.lang}")
        src = self.cfg["src"]

        if not os.path.isdir(debug_dir):
            print(f"[Per-Project] Debug CSV directory not found: {debug_dir}")
            return

        # TEST 디렉터리 아래 1단계 서브디렉터리를 프로젝트 목록으로 사용
        projects = []
        if os.path.isdir(src):
            for entry in sorted(os.listdir(src)):
                if os.path.isdir(os.path.join(src, entry)):
                    projects.append(entry)

        if not projects:
            print(f"[Per-Project] No project subdirectories found in {src}")
            return

        all_csv_names = set(os.listdir(debug_dir))

        for project in projects:
            prefix = project + "_"
            csv_files = sorted(
                os.path.join(debug_dir, f)
                for f in all_csv_names
                if f.startswith(prefix) and f.endswith(".csv")
            )
            if not csv_files:
                continue

            total = found = not_found = fail = beyond = 0
            top1 = top3 = top5 = top10 = top20 = 0
            file_reports = []

            for csv_path in csv_files:
                f_total = f_found = f_not_found = f_fail = 0
                f_top1 = f_top3 = f_top5 = f_top10 = f_top20 = 0

                with open(csv_path, "r", encoding="utf-8") as fh:
                    reader = csv.DictReader(fh)
                    for row in reader:
                        result = row.get("Coverage_Result", "")
                        try:
                            rank = int(row.get("Rank", "0"))
                        except ValueError:
                            rank = 0

                        f_total += 1
                        if result == "FOUND":
                            f_found += 1
                        elif result == "NOT_FOUND":
                            f_not_found += 1
                            if rank == 0:
                                beyond += 1
                        elif result == "FAIL":
                            f_fail += 1

                        if 0 < rank <= 1:  f_top1  += 1
                        if 0 < rank <= 3:  f_top3  += 1
                        if 0 < rank <= 5:  f_top5  += 1
                        if 0 < rank <= 10: f_top10 += 1
                        if 0 < rank <= 20: f_top20 += 1

                fname_base = os.path.basename(csv_path)[:-4]  # .csv 제거
                file_reports.append({
                    "name":      fname_base,
                    "total":     f_total,
                    "found":     f_found,
                    "not_found": f_not_found,
                    "fail":      f_fail,
                    "top1":      f_top1,
                    "top3":      f_top3,
                    "top5":      f_top5,
                    "top10":     f_top10,
                    "top20":     f_top20,
                })
                total     += f_total;     found    += f_found
                not_found += f_not_found; fail     += f_fail
                top1  += f_top1;  top3  += f_top3
                top5  += f_top5;  top10 += f_top10; top20 += f_top20

            if total == 0:
                continue

            # evaluate_struct_<lang>.py <project> 와 동일한 출력 형식
            lbl = project
            print(f"[{lbl}] Total Queries : {total}")
            print(f"[{lbl}] Top-10 Count  : {top10}")
            print(f"[{lbl}] Top11~20      : {top20 - top10}")
            print(f"[{lbl}] Beyond Top-20 : {beyond}")
            print(f"[{lbl}] CPP Fail      : {fail}")
            print()
            print(f"[{lbl}] Found         : {found}  ({found/total*100:.1f}%)")
            print(f"[{lbl}] Not Found     : {not_found}  ({not_found/total*100:.1f}%)")
            print(f"[{lbl}] Fail          : {fail}  ({fail/total*100:.1f}%)")

            # 프로젝트별 CSV 저장 (save_report 재사용)
            saved_reports    = self.file_reports
            self.file_reports = file_reports
            self.save_report(suffix=f"_{project}")
            self.file_reports = saved_reports
            print()

    def run(self):
        files = self._collect_files()
        print(f"[*] Language: {self.lang}")
        print(f"[*] Found {len(files)} target files. Starting evaluation...")

        start = time.time()
        for idx, f in enumerate(files):
            print(f" [{idx+1}/{len(files)}]", end=" ")
            self.evaluate_file(f)

        elapsed = time.time() - start
        print(f"\n[*] Analysis Complete in {elapsed:.2f} sec.\n")

        q = self.total_queries
        if q > 0:
            global_top10 = sum(self.rank_stats[r] for r in range(1, 11))
            global_top20 = sum(self.rank_stats[r] for r in range(1, 21))

            print(f"[Global] Total Queries    : {q}")
            print(f"[Global] Top-10 Count     : {global_top10}")
            print(f"[Global] Top-10 Acc       : {global_top10 / q * 100:.1f}%")
            print(f"[Global] Top11~20 Count   : {global_top20 - global_top10}")
            print(f"[Global] CPP Fail         : {self.fail_count}")

            print(f"[{self.lang.upper()}] Total Queries : {q}")
            print(f"[{self.lang.upper()}] Found         : {self.found_count}  ({self.found_count/q*100:.1f}%)")
            print(f"[{self.lang.upper()}] Not Found     : {self.not_found_count}  ({self.not_found_count/q*100:.1f}%)")
            print(f"[{self.lang.upper()}] Fail          : {self.fail_count}  ({self.fail_count/q*100:.1f}%)")

        self.save_report()


if __name__ == "__main__":
    # 사용법:
    #   python evaluate_coverage.py <language>
    #   python evaluate_coverage.py <language> --per-project
    #     → 전체 평가 후 이미 생성된 debug CSV를 프로젝트별로 재집계하여 추가 출력
    args = sys.argv[1:]
    per_project = "--per-project" in args
    pos_args = [a for a in args if not a.startswith("--")]

    if not pos_args:
        print(f"Usage: python evaluate_coverage.py <language> [--per-project]")
        print(f"Available: {', '.join(LANG_CONFIGS.keys())}")
        sys.exit(1)

    lang = pos_args[0].lower()
    if lang not in LANG_CONFIGS:
        print(f"[Error] Unknown language: '{lang}'")
        print(f"Available: {', '.join(LANG_CONFIGS.keys())}")
        sys.exit(1)

    reporter = EvaluationReporter(lang, LANG_CONFIGS[lang])
    reporter.run()

    if per_project:
        print("\n============================================================")
        print("  [Per-Project] Aggregating from existing debug CSVs...")
        print("============================================================\n")
        reporter.aggregate_per_project()
