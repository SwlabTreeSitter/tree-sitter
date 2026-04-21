#!/usr/bin/env bash
# =============================================================
# count_loc.sh
# 모든 언어의 LEARN/TEST 프로젝트별 LOC를 측정한다.
# lang_config.json의 제외 디렉터리를 반영한다.
#   - wc -l: 총 라인 수
#   - cloc:  코드/주석/공백 분리
#
# 출력: loc_report.csv
# =============================================================

set -uo pipefail
export LANG=C LC_ALL=C

BASE="/home/hyeonjin/PL/codecompletion_benchmarks"
TS_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="$TS_DIR/lang_config.json"
OUTFILE="$TS_DIR/loc_report.csv"

# 언어 설정: "표시명|서브디렉토리|LEARN폴더|TEST폴더|확장자(공백구분)|cloc추가옵션|프로젝트서브디렉토리여부"
CONFIGS=(
  "c|c|LEARN|TEST|c||yes"
  "cpp|cpp|LEARN|TEST|cpp cc cxx||yes"
  "haskell|haskell|LEARN|TEST|hs||yes"
  "java|java|LEARN|TEST|java||yes"
  "javascript|javascript|LEARN|TEST|js||yes"
  "php|php|LEARN|TEST|php||yes"
  "python|python|LEARN|TEST|py||yes"
  "ruby|ruby|LEARN|TEST|rb||yes"
  "smallbasic|smallbasic|LEARN|TEST|sb|--force-lang=Visual Basic,sb|no"
)

# lang_config.json에서 제외 디렉터리 목록 추출
get_ignore_dirs() {
  local lang="$1"
  python3 -c "
import json, sys
with open('$CONFIG_FILE') as f:
    cfg = json.load(f)
common = set(cfg.get('_common', {}).get('ignore_dirs', []))
lang_cfg = cfg.get('$lang', {})
extra = set(lang_cfg.get('extra_ignore_dirs', []))
for d in sorted(common | extra):
    print(d)
" 2>/dev/null
}

count_and_emit() {
  local lang="$1" set_display="$2" project="$3" dir="$4" exts="$5" cloc_extra="$6" ignore_dirs="$7"

  # --- find 제외 인자 구성 ---
  local prune_args=()
  while IFS= read -r igd; do
    [ -z "$igd" ] && continue
    prune_args+=( -name "$igd" -o )
  done <<< "$ignore_dirs"

  # --- find 확장자 인자 구성 ---
  local find_args=()
  local first=true
  for ext in $exts; do
    if [ "$first" = true ]; then
      find_args+=( -name "*.${ext}" )
      first=false
    else
      find_args+=( -o -name "*.${ext}" )
    fi
  done

  # --- wc 카운트 (제외 디렉터리 반영) ---
  local wc_total=0
  if [ ${#prune_args[@]} -gt 0 ]; then
    # prune_args의 마지막 -o 제거
    unset 'prune_args[-1]'
    wc_total="$(find "$dir" \( -type d \( "${prune_args[@]}" \) -prune \) -o \( -type f \( "${find_args[@]}" \) -print0 \) 2>/dev/null \
      | xargs -0 wc -l 2>/dev/null \
      | awk '$NF ~ /\// {s+=$1} END{print s+0}')"
  else
    wc_total="$(find "$dir" \( "${find_args[@]}" \) -print0 2>/dev/null \
      | xargs -0 wc -l 2>/dev/null \
      | awk '$NF ~ /\// {s+=$1} END{print s+0}')"
  fi

  # --- cloc 카운트 (제외 디렉터리 반영) ---
  local ext_list
  ext_list="$(echo "$exts" | tr ' ' ',')"

  # cloc --exclude-dir 인자 구성
  local cloc_exclude=""
  if [ -n "$ignore_dirs" ]; then
    cloc_exclude="--exclude-dir=$(echo "$ignore_dirs" | tr '\n' ',' | sed 's/,$//')"
  fi

  local cloc_files=0 cloc_code=0 cloc_comment=0 cloc_blank=0
  local cloc_output
  local cloc_cmd=(/usr/bin/cloc --csv --quiet --skip-uniqueness --include-ext="$ext_list")
  [ -n "$cloc_exclude" ] && cloc_cmd+=("$cloc_exclude")
  [ -n "$cloc_extra" ] && cloc_cmd+=("$cloc_extra")
  cloc_cmd+=("$dir")

  cloc_output="$("${cloc_cmd[@]}" 2>/dev/null || true)"

  if [ -n "$cloc_output" ]; then
    local sum_line
    sum_line="$(echo "$cloc_output" | grep ',SUM,' || true)"
    if [ -n "$sum_line" ]; then
      cloc_files="$(echo "$sum_line" | cut -d',' -f1)"
      cloc_blank="$(echo "$sum_line" | cut -d',' -f3)"
      cloc_comment="$(echo "$sum_line" | cut -d',' -f4)"
      cloc_code="$(echo "$sum_line" | cut -d',' -f5)"
    else
      # 단일 언어일 때 SUM 행이 없을 수 있음 — 마지막 데이터 행 사용
      local data_line
      data_line="$(echo "$cloc_output" | tail -1)"
      if echo "$data_line" | grep -qE '^[0-9]'; then
        cloc_files="$(echo "$data_line" | cut -d',' -f1)"
        cloc_blank="$(echo "$data_line" | cut -d',' -f3)"
        cloc_comment="$(echo "$data_line" | cut -d',' -f4)"
        cloc_code="$(echo "$data_line" | cut -d',' -f5)"
      fi
    fi
  fi

  echo "${lang},${set_display},${project},${cloc_files},${wc_total},${cloc_code},${cloc_comment},${cloc_blank}"
}

# --- 메인 ---
echo "Language,Set,Project,Files,Total_Lines_wc,Code_Lines_cloc,Comment_Lines_cloc,Blank_Lines_cloc" > "$OUTFILE"

for config in "${CONFIGS[@]}"; do
  IFS='|' read -r lang subdir learn_dir test_dir exts cloc_extra has_projects <<< "$config"

  # 제외 디렉터리 목록 취득
  ignore_dirs="$(get_ignore_dirs "$lang")"

  for set_name in "$learn_dir" "$test_dir"; do
    local_display="${set_name%%_BENCH}"

    dir="$BASE/$subdir/$set_name"
    [ -d "$dir" ] || continue

    if [ "$has_projects" = "yes" ]; then
      while IFS= read -r -d '' proj_dir; do
        proj_name="$(basename "$proj_dir")"
        # 제외 디렉터리와 temp 스킵
        case "$proj_name" in .git|temp) continue ;; esac
        echo "  [$lang] $local_display / $proj_name ..." >&2
        count_and_emit "$lang" "$local_display" "$proj_name" "$proj_dir" "$exts" "$cloc_extra" "$ignore_dirs" >> "$OUTFILE"
      done < <(find "$dir" -maxdepth 1 -mindepth 1 -type d -print0 | sort -z)
    else
      echo "  [$lang] $local_display / all ..." >&2
      count_and_emit "$lang" "$local_display" "all" "$dir" "$exts" "$cloc_extra" "$ignore_dirs" >> "$OUTFILE"
    fi
  done
done

echo "" >&2
echo "Done. Output: $OUTFILE" >&2
